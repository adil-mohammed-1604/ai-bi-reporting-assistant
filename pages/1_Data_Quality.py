import plotly.express as px
import streamlit as st

from src import config
from src.data_quality import RULES
from src.export_utils import to_safe_csv
from src.ui_helpers import require_upload

st.set_page_config(page_title="Data Quality", layout="wide")
st.title("Data Quality")

upload = require_upload()
quality, profile = upload["quality"], upload["profile"]
s, issues, data = quality.summary, quality.issues, quality.data
st.caption(f"File: {upload['name']}")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Original rows", f"{s['original_rows']:,}")
c2.metric("Accepted", f"{s['accepted_rows']:,}")
c3.metric("Flagged", f"{s['flagged_rows']:,}")
c4.metric("Rejected", f"{s['rejected_rows']:,}")
c5.metric("Acceptance rate", f"{s['acceptance_rate']}%")
st.caption("Flagged rows are kept but excluded from KPIs where the rules say so. "
           "Rejected rows can't be used at all. Nothing is deleted.")

# ------------------------------------------------------------------ issues
st.subheader("Issues found")
if issues.empty:
    st.success("No issues found.")
else:
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(issues, use_container_width=True, hide_index=True)
    with right:
        fig = px.bar(issues.sort_values("IssueCount"), x="IssueCount", y="IssueType",
                     color="Severity", orientation="h", text="IssueCount",
                     category_orders={"Severity": list(reversed(config.SEVERITIES))},
                     color_discrete_map={"ERROR": "#C0392B", "WARNING": "#D68910", "INFO": "#2E86C1"})
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), yaxis_title=None,
                          legend_title_text="Severity")
        st.plotly_chart(fig, use_container_width=True)

st.subheader("Missing values by column")
miss = profile["column_profile"]
fig2 = px.bar(miss, x="Column", y="Missing %", text="Missing")
fig2.update_traces(textposition="outside")
fig2.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Missing (%)")
st.plotly_chart(fig2, use_container_width=True)

with st.expander("Rules applied"):
    for name, (column, severity, effect, details) in RULES.items():
        outcome = {"reject": "row rejected", "flag": "row flagged", "note": "recorded only"}[effect]
        st.markdown(f"- **{name}** ({severity}, {outcome}) on `{column}`: {details}")

# ------------------------------------------------------------------ row-level review
st.subheader("Review rows")
cols = ["SourceRow"] + config.ALL_COLUMNS + ["Status", "Reasons"]
tab_rej, tab_flag = st.tabs([f"Rejected ({s['rejected_rows']:,})", f"Flagged ({s['flagged_rows']:,})"])

for tab, frame, label, key in [(tab_rej, quality.rejected, "rejected rows", "rej"),
                               (tab_flag, quality.flagged, "flagged rows", "flag")]:
    with tab:
        if frame.empty:
            st.info(f"No {label}.")
            continue
        reasons = sorted({r for cell in frame["Reasons"] for r in cell.split(";") if r})
        pick = st.multiselect("Filter by reason", reasons, key=f"filter_{key}")
        shown = frame[frame["Reasons"].apply(lambda c: not pick or any(p in c.split(";") for p in pick))]
        st.dataframe(shown[cols].head(500), use_container_width=True, hide_index=True)
        if len(shown) > 500:
            st.caption(f"Showing the first 500 of {len(shown):,}. The download has all of them.")
        st.download_button(f"Download {label} (CSV)", to_safe_csv(shown[cols]),
                           file_name=f"{label.replace(' ', '_')}.csv", mime="text/csv", key=f"dl_{key}")

st.divider()
st.download_button("Download data-quality issue report (CSV)", to_safe_csv(issues),
                   file_name="data_quality_issues.csv", mime="text/csv", key="dl_issues",
                   disabled=issues.empty)