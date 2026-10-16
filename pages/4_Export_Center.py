import streamlit as st

from src import ai_report, config
from src.export_utils import build_kpi_workbook, to_safe_csv
from src.ui_helpers import require_upload

st.set_page_config(page_title="Export Center", layout="wide")
st.title("Export Center")

upload = require_upload()
quality, kpis = upload["quality"], upload["kpis"]
data = quality.data
db = upload.get("db")
reconciled = None if db is None else bool(db["rec"]["ok"])
run_id = None if db is None else db["run_id"]
report = upload.get("report")
stem = upload["name"].rsplit(".", 1)[0]

st.caption(f"File: {upload['name']}")
if reconciled is False:
    st.warning(f"Python and SQL disagree for run #{run_id}. Exports are marked accordingly; "
               "treat the figures as unverified.")
elif reconciled is None:
    st.info("These figures have not been reconciled with SQL yet (see the Home page).")

cols = ["SourceRow"] + config.ALL_COLUMNS + ["Status", "Reasons"]

# ------------------------------------------------------------------ KPI workbook
st.subheader("KPI summary workbook (Excel)")
st.write("Summary with definitions and limitations, monthly / country / product tables, the data-quality "
         "results, and the rejected and flagged rows. Text from your file is stored as plain text, never as formulas.")
if kpis is None:
    st.error("No eligible rows, so there are no KPIs to export. The data-quality files below are still available.")
else:
    workbook = build_kpi_workbook(upload["name"], upload["hash"], quality, kpis, run_id, reconciled, report)
    st.download_button("Download KPI workbook (.xlsx)", workbook, file_name=f"{stem}_kpi_summary.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_xlsx")

# ------------------------------------------------------------------ data quality
st.subheader("Data-quality files (CSV)")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.download_button("Issue report", to_safe_csv(quality.issues), file_name=f"{stem}_quality_issues.csv",
                       mime="text/csv", key="dl_issues", disabled=quality.issues.empty, use_container_width=True)
with c2:
    st.download_button(f"Rejected rows ({quality.summary['rejected_rows']:,})", to_safe_csv(quality.rejected[cols]),
                       file_name=f"{stem}_rejected_rows.csv", mime="text/csv", key="dl_rejected",
                       disabled=quality.rejected.empty, use_container_width=True)
with c3:
    st.download_button(f"Flagged rows ({quality.summary['flagged_rows']:,})", to_safe_csv(quality.flagged[cols]),
                       file_name=f"{stem}_flagged_rows.csv", mime="text/csv", key="dl_flagged",
                       disabled=quality.flagged.empty, use_container_width=True)
with c4:
    kept = data[data["Status"] != "REJECTED"][cols]
    st.download_button(f"Validated data ({len(kept):,})", to_safe_csv(kept), file_name=f"{stem}_validated_data.csv",
                       mime="text/csv", key="dl_validated", disabled=kept.empty, use_container_width=True)
st.caption("Validated data = accepted plus flagged rows, with each row's status and reasons. "
           "Rejected rows are never deleted from your original file.")

# ------------------------------------------------------------------ report
st.subheader("Report draft")
if report is None:
    st.info("No report yet. Create one on the AI Report page and it will be available here.")
elif report.status != "VERIFIED":
    st.error("The current report draft has numbers that could not be verified, so it can't be exported.")
else:
    st.download_button("Download report draft (Markdown)", ai_report.report_to_markdown(report),
                       file_name=f"{stem}_report_draft.md", mime="text/markdown", key="dl_report")
    st.caption("Verified draft. A person must review it before use. It is also included as a sheet in the workbook.")