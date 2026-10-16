"""Safe file ingestion for CSV and XLSX uploads.

Everything is read as text (dtype=str) so that bad values such as "abc" or
"not a date" survive loading and can be flagged by the quality engine instead
of crashing the read. Formulas and macros are never executed: openpyxl only
returns cached cell values, and .xlsm / .xls files are rejected outright.
"""
import io
from pathlib import Path

import pandas as pd

from src import config


class LoaderError(Exception):
    """Raised for any problem the user should see as a clear message."""


def _read_bytes(source) -> tuple[bytes, str]:
    """Accept a file path or an uploaded-file object (e.g. Streamlit UploadedFile)."""
    if hasattr(source, "read"):
        name = getattr(source, "name", "") or ""
        return source.read(), name
    path = Path(source)
    if not path.exists():
        raise LoaderError(f"File not found: {path.name}")
    return path.read_bytes(), path.name


def _canonical_columns(columns) -> dict:
    """Map case-insensitive, whitespace-trimmed headers to the expected names."""
    expected = {c.lower(): c for c in config.ALL_COLUMNS}
    mapping = {}
    for col in columns:
        key = str(col).strip().lower()
        mapping[col] = expected.get(key, str(col).strip())
    return mapping


def load_file(source) -> pd.DataFrame:
    """Load a CSV/XLSX into an all-text DataFrame with a SourceRow column.

    Raises LoaderError with a readable message for unsupported types, oversize
    files, unreadable files, empty files and missing required columns.
    """
    data, name = _read_bytes(source)
    ext = Path(name).suffix.lower()

    if ext not in config.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(config.ALLOWED_EXTENSIONS))
        raise LoaderError(f"Unsupported file type '{ext or 'unknown'}'. Please upload one of: {allowed}.")

    size_mb = len(data) / (1024 * 1024)
    if size_mb > config.MAX_UPLOAD_MB:
        raise LoaderError(f"File is {size_mb:.1f} MB; the limit is {config.MAX_UPLOAD_MB} MB.")
    if len(data) == 0:
        raise LoaderError("The file is empty.")

    buffer = io.BytesIO(data)
    try:
        if ext == ".csv":
            # keep_default_na=False so text like "N/A" stays visible as a bad value;
            # only truly empty cells become missing.
            df = pd.read_csv(buffer, dtype=str, keep_default_na=False, na_values=[""],
                             encoding="utf-8-sig")
        else:
            df = pd.read_excel(buffer, dtype=str, engine="openpyxl")
    except Exception as exc:  # parser errors vary widely; report plainly
        raise LoaderError(f"The file could not be read as {ext}: {exc}") from exc

    if df.empty:
        raise LoaderError("The file has a header but no data rows.")

    df = df.rename(columns=_canonical_columns(df.columns))

    missing = [c for c in config.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise LoaderError("Missing required column(s): " + ", ".join(missing)
                          + ". Expected at least: " + ", ".join(config.REQUIRED_COLUMNS) + ".")

    # Add optional columns if absent so later code can rely on them.
    for col in config.OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    # Strip whitespace in text cells; keep the original row number for traceability.
    df = df[config.ALL_COLUMNS].apply(lambda s: s.str.strip())
    df.insert(0, "SourceRow", range(1, len(df) + 1))
    return df