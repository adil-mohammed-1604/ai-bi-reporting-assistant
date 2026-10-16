import streamlit as st

from src import ai_report, config
from src.ui_helpers import require_upload

st.set_page_config(page_title="AI Report", layout="wide")
st.title("AI Report")
st.caption("A draft narrative written from the verified KPIs. The numbers come from Python and SQL; "
           "the writing can come from an AI model or from a built-in template.")

upload = require_upload()
kpis = upload["kpis"]
if kpis is None:
    st.error("No eligible rows, so there are no KPIs to report on. See the Data Quality page.")
    st.stop()


def md(text: str) -> str:
    return text.replace("$", r"\$")       # keep dollar signs from being read as maths


db = upload.get("db")
reconciled = None if db is None else bool(db["rec"]["ok"])
blocked = reconciled is False

if blocked:
    st.error(f"Blocked: Python and SQL results disagree for run #{db['run_id']}. "
             "A report built on unverified KPIs could mislead, so none can be generated until the "
             "difference is reviewed (see the Home page).")
elif reconciled is None:
    st.info("These KPIs have not been reconciled with SQL yet. You can still draft a report, but it will "
            "say so. Use **Save run to SQL Server** on the Home page to reconcile first.")
else:
    st.success(f"KPIs reconciled between Python and SQL (run #{db['run_id']}).")

# ------------------------------------------------------------------ what is sent
payload = ai_report.build_payload(kpis, reconciled)
with st.expander("Exactly what the AI receives"):
    st.caption("Aggregated figures, definitions and caveats only. No raw rows, invoice numbers or customer IDs "
               "are sent. Product descriptions come from your file and are shortened and cleaned first.")
    st.json(payload, expanded=False)

# ------------------------------------------------------------------ generate
has_key = bool(config.LLM_API_KEY)
st.markdown(f"**AI provider:** `{config.LLM_PROVIDER}`  |  **model:** `{config.LLM_MODEL}`  |  "
            f"**API key:** {'found' if has_key else 'not set'}")
if not has_key:
    st.info("To use an AI model, put your key in `.env` as `LLM_API_KEY=...` and restart the app. "
            "The template report below works without a key.")

b1, b2, _ = st.columns([1, 1, 2])
run_ai = b1.button("Generate AI draft", key="gen_ai", disabled=blocked or not has_key, type="primary")
run_tpl = b2.button("Generate template report (no AI)", key="gen_template", disabled=blocked)

if run_ai:
    try:
        with st.spinner(f"Asking {config.LLM_PROVIDER}..."):
            upload["report"] = ai_report.generate_report(kpis, reconciled)
    except ai_report.AIReportError as exc:
        st.error(f"The AI draft could not be produced, but everything else still works. {exc}")
if run_tpl:
    upload["report"] = ai_report.generate_template_report(kpis, reconciled)

# ------------------------------------------------------------------ show
report = upload.get("report")
if report is None:
    st.stop()

st.divider()
c = report.content
source = "Rule-based template (no AI)" if report.provider == "template" else f"{report.provider} / {report.model}"
st.warning("**Draft.** A person must review this before it is used for any decision. "
           "Trends shown here do not prove their causes.")

if report.status == "VERIFIED":
    st.success("Every number in this draft was traced back to the verified metrics.")
else:
    st.error("**Not verified.** This draft contains numbers that could not be traced to the verified "
             f"metrics: {', '.join(report.unverified)}. Do not use it. Generate it again, "
             "or use the template report.")

show = report.status == "VERIFIED"
if not show:
    show = st.checkbox("Show the unverified draft anyway (for inspection only)", key="show_unverified")

if show:
    st.subheader("Executive summary")
    st.write(md(c["executive_summary"]))
    st.subheader("Key findings")
    for item in c["key_findings"]:
        st.markdown("- " + md(item))
    st.subheader("Suggested follow-up analysis")
    for item in c["follow_up_analysis"]:
        st.markdown("- " + md(item))
    st.subheader("Limitations")
    for item in c["limitations"]:
        st.markdown("- " + md(item))

rec_text = {True: "Python and SQL agreed", False: "Python and SQL disagreed", None: "not reconciled with SQL"}[report.reconciled]
st.caption(f"Source: {source}  |  Generated: {report.generated_at}  |  Period: {report.period}  |  "
           f"{rec_text}  |  Input fingerprint: {report.payload_hash}  |  Status: {report.status}")
st.download_button("Download report (Markdown)", ai_report.report_to_markdown(report),
                   file_name="business_report_draft.md", mime="text/markdown", key="dl_report",
                   disabled=report.status != "VERIFIED")