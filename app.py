import hashlib

import streamlit as st

from src import config
from src.data_loader import LoaderError
from src.database import (DatabaseError, check_schema, reconcile, run_sql_kpis,
                          save_run)
from src.ui_helpers import SAMPLE_PATH, process

st.set_page_config(page_title="BI Assistant", layout="wide")

st.title("AI-Powered Business Intelligence & Reporting Assistant")
st.caption("Upload a dataset, check its quality, calculate verified KPIs, and draft a report. "
           "Numbers always come from Python and SQL; AI only explains them.")

# ------------------------------------------------------------------ upload
left, right = st.columns([4, 1], vertical_alignment="bottom")
with left:
    uploaded = st.file_uploader(
        "Upload a CSV or Excel (.xlsx) file", type=["csv", "xlsx"],
        help=f"Up to {config.MAX_UPLOAD_MB} MB. Formulas and macros are never executed.")
with right:
    use_sample = st.button("Use sample dataset", key="load_sample", use_container_width=True)

try:
    if uploaded is not None:
        data = uploaded.getvalue()
        current = st.session_state.get("upload")
        if current is None or current["hash"] != hashlib.sha256(data).hexdigest():
            with st.spinner("Reading and validating the file..."):
                st.session_state["upload"] = process(data, uploaded.name)
    elif use_sample:
        with st.spinner("Loading the sample dataset..."):
            st.session_state["upload"] = process(SAMPLE_PATH.read_bytes(), SAMPLE_PATH.name)
except LoaderError as exc:
    st.error(f"**This file can't be used.** {exc}")

upload = st.session_state.get("upload")
if upload is None:
    st.info("Upload a file, or click **Use sample dataset** to try the app.")
    st.markdown("**Expected columns** (required marked with *)")
    st.table({
        "Column": [c + " *" for c in config.REQUIRED_COLUMNS] + config.OPTIONAL_COLUMNS,
        "Meaning": ["Invoice / order id (starts with C = cancellation)", "Product id",
                    "Units sold", "Transaction date and time", "Price per unit",
                    "Product description", "Customer id", "Country or market"],
    })
    st.stop()

profile, quality = upload["profile"], upload["quality"]
s = quality.summary

# ------------------------------------------------------------------ profile
st.subheader(f"Dataset: {upload['name']}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Rows", f"{profile['rows']:,}")
c2.metric("Columns", profile["columns"])
c3.metric("Date range", f"{(profile['date_min'] or '-')[:10]} to {(profile['date_max'] or '-')[:10]}")
c4.metric("Exact duplicate rows", f"{profile['exact_duplicate_rows']:,}")

with st.expander("Preview (first 20 rows)", expanded=True):
    st.dataframe(upload["raw"].drop(columns=["SourceRow"]).head(20), use_container_width=True, hide_index=True)
with st.expander("Column profile"):
    st.dataframe(profile["column_profile"], use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ validation status
st.subheader("Validation status")
v1, v2, v3, v4 = st.columns(4)
v1.metric("Accepted", f"{s['accepted_rows']:,}")
v2.metric("Flagged for review", f"{s['flagged_rows']:,}")
v3.metric("Rejected", f"{s['rejected_rows']:,}")
v4.metric("Acceptance rate", f"{s['acceptance_rate']}%")

if not s["can_analyze"]:
    st.error("No usable rows: every record was rejected or excluded, so KPIs can't be calculated. "
             "See the Data Quality page for the reasons.")
else:
    st.success(f"{s['eligible_rows']:,} of {s['original_rows']:,} rows are eligible for analysis. "
               "Nothing was deleted; every flagged or rejected row is kept for review.")
st.page_link("pages/1_Data_Quality.py", label="Review data quality in detail")

# ------------------------------------------------------------------ database
st.subheader("Save to SQL Server and reconcile")
st.caption("Stores the validated rows, then recalculates the KPIs in SQL and compares them with Python.")

if st.button("Save run to SQL Server", key="save_db", disabled=not s["can_analyze"]):
    try:
        with st.spinner("Saving and reconciling..."):
            check_schema()
            run_id = save_run(upload["name"], quality, file_hash=upload["hash"])
            rec = reconcile(upload["kpis"], run_sql_kpis(run_id))
        upload["db"] = {"run_id": run_id, "rec": rec}
    except DatabaseError as exc:
        upload["db"] = None
        st.error(f"The database step failed, but the rest of the app still works. {exc}")

if upload.get("db"):
    db = upload["db"]
    if db["rec"]["ok"]:
        st.success(f"Run #{db['run_id']} is stored. Python and SQL results agree.")
    else:
        st.warning(f"Run #{db['run_id']} is stored, but Python and SQL **do not agree**. "
                   "Reports built from this run need review.")
        st.dataframe(db["rec"]["monthly_mismatches"], hide_index=True)
    st.dataframe(db["rec"]["checks"], use_container_width=True, hide_index=True)