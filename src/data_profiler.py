"""Dataset profiling: shape, per-column quality summary, numeric stats, date range."""
import pandas as pd


def profile_columns(df: pd.DataFrame) -> pd.DataFrame:
    """One row per column: missing count/%, distinct count and a sample value."""
    rows = []
    n = len(df)
    for col in df.columns:
        if col == "SourceRow":
            continue
        s = df[col]
        missing = int(s.isna().sum())
        rows.append({
            "Column": col,
            "Missing": missing,
            "Missing %": round(100 * missing / n, 2) if n else 0.0,
            "Distinct": int(s.nunique(dropna=True)),
            "Example": s.dropna().iloc[0] if missing < n else None,
        })
    return pd.DataFrame(rows)


def profile_dataset(df: pd.DataFrame) -> dict:
    """Overall profile used by the Upload and Data Quality pages."""
    qty = pd.to_numeric(df["Quantity"], errors="coerce")
    price = pd.to_numeric(df["UnitPrice"], errors="coerce")
    dates = pd.to_datetime(df["InvoiceDate"], errors="coerce")

    def stats(s: pd.Series) -> dict:
        valid = s.dropna()
        if valid.empty:
            return {"valid": 0}
        return {"valid": int(valid.count()), "min": float(valid.min()),
                "max": float(valid.max()), "mean": round(float(valid.mean()), 2)}

    valid_dates = dates.dropna()
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns) - (1 if "SourceRow" in df.columns else 0)),
        "exact_duplicate_rows": int(df.drop(columns=["SourceRow"], errors="ignore").duplicated().sum()),
        "quantity": stats(qty),
        "unit_price": stats(price),
        "non_numeric_quantity": int(qty.isna().sum() - df["Quantity"].isna().sum()),
        "non_numeric_price": int(price.isna().sum() - df["UnitPrice"].isna().sum()),
        "unparseable_dates": int(dates.isna().sum() - df["InvoiceDate"].isna().sum()),
        "date_min": str(valid_dates.min()) if not valid_dates.empty else None,
        "date_max": str(valid_dates.max()) if not valid_dates.empty else None,
        "column_profile": profile_columns(df),
    }