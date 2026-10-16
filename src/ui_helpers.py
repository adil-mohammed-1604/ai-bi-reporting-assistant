"""Shared Streamlit helpers: processing an upload and guarding pages that need one."""
import hashlib
import io

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from src import config
from src.analytics import AnalyticsError, compute_kpis
from src.data_loader import load_file
from src.data_profiler import profile_dataset
from src.data_quality import run_quality_checks

SAMPLE_PATH = config.BASE_DIR / "data" / "sample_retail_transactions.csv"


class _NamedBytes(io.BytesIO):
    """In-memory file with a name, so the loader can check the extension."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def process(data: bytes, name: str) -> dict:
    """Load, profile, validate and calculate KPIs for one file.

    Raises LoaderError (a readable message) for unusable files. If every row
    is rejected, kpis is None and the pages explain why.
    """
    raw = load_file(_NamedBytes(data, name))
    quality = run_quality_checks(raw)
    try:
        kpis = compute_kpis(quality)
    except AnalyticsError:
        kpis = None
    return {
        "name": name,
        "hash": hashlib.sha256(data).hexdigest(),
        "raw": raw,
        "profile": profile_dataset(raw),
        "quality": quality,
        "kpis": kpis,
        "db": None,          # filled after "Save to SQL Server"
    }


def require_upload() -> dict:
    """Return the current upload, or show a friendly message and stop the page."""
    upload = st.session_state.get("upload")
    if upload is None:
        st.info("No dataset loaded yet. Go to the Home page and upload a file, "
                "or use the sample dataset.")
        try:
            st.page_link("app.py", label="Go to Home / Upload")
        except StreamlitPageNotFoundError:
            pass   # page opened outside the multipage app; the message above is enough
        st.stop()
    return upload