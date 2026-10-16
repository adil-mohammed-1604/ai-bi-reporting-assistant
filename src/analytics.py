"""KPI calculations (Python side).

All functions work on ELIGIBLE rows only (see docs/metric_dictionary.md):
not rejected, not a cancellation, Quantity > 0 and UnitPrice > 0.

Every KPI is returned as a structured record:
    {name, value, period, definition, limitations}
so reports, exports and the AI step all work from the same verified numbers.
"""
import pandas as pd

from src.data_quality import QualityResult


class AnalyticsError(Exception):
    """Raised when KPIs cannot be calculated (for example, no eligible rows)."""


# ---------------------------------------------------------------- KPI functions
def total_revenue(elig: pd.DataFrame) -> float:
    return round(float(elig["LineRevenue"].sum()), 2)


def distinct_orders(elig: pd.DataFrame) -> int:
    return int(elig["InvoiceNo"].nunique())


def average_order_value(elig: pd.DataFrame) -> float:
    """Average of ORDER-level totals (not the average of transaction lines)."""
    order_totals = elig.groupby("InvoiceNo")["LineRevenue"].sum()
    return round(float(order_totals.mean()), 2)


def unique_customers(elig: pd.DataFrame) -> int:
    ids = elig["CustomerID"].dropna()
    ids = ids[ids.astype("string").str.strip() != ""]
    return int(ids.nunique())


def revenue_growth(current: float, previous) -> float | None:
    """(current - previous) / previous x 100; None when previous is 0 or missing."""
    if previous is None or pd.isna(previous) or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def monthly_revenue(elig: pd.DataFrame) -> pd.DataFrame:
    month = elig["InvoiceDateValue"].dt.to_period("M").astype(str)
    g = elig.groupby(month)
    out = pd.DataFrame({
        "Month": g["LineRevenue"].sum().index,
        "Revenue": g["LineRevenue"].sum().round(2).values,
        "Orders": g["InvoiceNo"].nunique().values,
    })
    return out.sort_values("Month").reset_index(drop=True)


def country_revenue(elig: pd.DataFrame) -> pd.DataFrame:
    country = elig["Country"].fillna("Unknown")
    g = elig.groupby(country)
    out = pd.DataFrame({
        "Country": g["LineRevenue"].sum().index,
        "Revenue": g["LineRevenue"].sum().round(2).values,
        "Orders": g["InvoiceNo"].nunique().values,
    })
    return out.sort_values("Revenue", ascending=False).reset_index(drop=True)


def top_products(elig: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    g = elig.groupby("StockCode")
    out = pd.DataFrame({
        "StockCode": g["LineRevenue"].sum().index,
        "Description": g["Description"].first().values,   # first non-missing value
        "Revenue": g["LineRevenue"].sum().round(2).values,
        "UnitsSold": g["QuantityValue"].sum().astype(int).values,
    })
    return out.sort_values("Revenue", ascending=False).head(n).reset_index(drop=True)


# ---------------------------------------------------------------- orchestration
def _metric(name, value, period, definition, limitations="") -> dict:
    return {"name": name, "value": value, "period": period,
            "definition": definition, "limitations": limitations}


def compute_kpis(result: QualityResult) -> dict:
    """Calculate every KPI plus the tables behind the dashboard charts."""
    elig = result.eligible
    if elig.empty:
        raise AnalyticsError("No eligible rows: every record was rejected or excluded, "
                             "so KPIs cannot be calculated. Check the Data Quality page.")

    start, end = elig["InvoiceDateValue"].min(), elig["InvoiceDateValue"].max()
    period = f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"

    monthly = monthly_revenue(elig)
    growth, growth_note = None, "Needs at least two months of data."
    if len(monthly) >= 2:
        cur, prev = monthly.iloc[-1], monthly.iloc[-2]
        growth = revenue_growth(float(cur["Revenue"]), float(prev["Revenue"]))
        growth_note = (f"Compares {cur['Month']} with {prev['Month']}. "
                       "A partial final month will understate growth.")

    s = result.summary
    excluded = s["original_rows"] - s["eligible_rows"]
    missing_cust = int(elig["CustomerID"].isna().sum())

    metrics = [
        _metric("Total revenue", total_revenue(elig), period,
                "Sum of Quantity x UnitPrice over eligible rows.",
                "Excludes cancellations, non-positive quantity/price and rejected rows. "
                "Currency is not specified in the data."),
        _metric("Distinct orders", distinct_orders(elig), period,
                "Count of distinct InvoiceNo over eligible rows.",
                "Counts invoices, not transaction rows."),
        _metric("Average order value", average_order_value(elig), period,
                "Average of order-level revenue totals over eligible invoices.",
                "Based on eligible invoices only."),
        _metric("Unique customers", unique_customers(elig), period,
                "Count of distinct non-missing CustomerID over eligible rows.",
                (f"{missing_cust} eligible rows have no CustomerID, so this is a lower bound."
                 if missing_cust else "Every eligible row has a CustomerID.")),
        _metric("Revenue growth % (latest month vs previous)", growth, period,
                "(latest month - previous month) / previous month x 100.", growth_note),
        _metric("Data acceptance rate %", s["acceptance_rate"], "all uploaded rows",
                "Rows not rejected / original rows x 100.",
                "Flagged rows (cancellations, duplicates, non-positive values) count as accepted "
                "but flagged rows that are not eligible are excluded from the KPIs above."),
    ]

    return {
        "period": period,
        "metrics": metrics,
        "values": {m["name"]: m["value"] for m in metrics},
        "monthly": monthly,
        "countries": country_revenue(elig),
        "products": top_products(elig),
        "exclusions": {
            "original_rows": s["original_rows"],
            "eligible_rows": s["eligible_rows"],
            "excluded_rows": excluded,
            "rejected_rows": s["rejected_rows"],
            "flagged_rows": s["flagged_rows"],
        },
    }