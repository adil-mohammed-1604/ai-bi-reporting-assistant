"""Data-quality engine.

Classifies every row as ACCEPTED, FLAGGED or REJECTED using the rules in
docs/metric_dictionary.md, and builds an issue summary shaped like the
DataQualityIssues table (ColumnName, IssueType, Severity, IssueCount, Details).

Nothing is ever deleted: the original rows are preserved and each row carries
its status and reasons. A row is ELIGIBLE (used by KPIs) when it is not
rejected, not a cancellation, and has Quantity > 0 and UnitPrice > 0.
"""
from dataclasses import dataclass

import pandas as pd

from src import config

# Rule table: (IssueType, column, severity, effect, details)
# effect: "reject" -> row REJECTED, "flag" -> row FLAGGED, "note" -> recorded only
RULES = {
    "MISSING_INVOICE":      ("InvoiceNo",   "ERROR",   "reject", "InvoiceNo is missing."),
    "INVALID_DATE":         ("InvoiceDate", "ERROR",   "reject", "InvoiceDate is missing or cannot be parsed as a date."),
    "INVALID_QUANTITY":     ("Quantity",    "ERROR",   "reject", "Quantity is missing or not numeric."),
    "INVALID_PRICE":        ("UnitPrice",   "ERROR",   "reject", "UnitPrice is missing or not numeric."),
    "CANCELLATION":         ("InvoiceNo",   "INFO",    "flag",   f"Invoice starts with '{config.CANCELLATION_PREFIX}'; excluded from KPIs."),
    "NON_POSITIVE_QUANTITY": ("Quantity",   "WARNING", "flag",   "Quantity is zero or negative on a non-cancellation; excluded from KPIs."),
    "NON_POSITIVE_PRICE":   ("UnitPrice",   "WARNING", "flag",   "UnitPrice is zero or negative; excluded from KPIs."),
    "DUPLICATE_ROW":        ("(all)",       "WARNING", "flag",   "Exact repeat of an earlier row; kept and counted, never silently deleted."),
    "MISSING_CUSTOMER_ID":  ("CustomerID",  "WARNING", "note",   "CustomerID is missing; row still counts toward revenue."),
    "MISSING_DESCRIPTION":  ("Description", "INFO",    "note",   "Description is missing."),
    "MISSING_COUNTRY":      ("Country",     "INFO",    "note",   "Country is missing."),
}


@dataclass
class QualityResult:
    data: pd.DataFrame      # every original row + parsed values + Status/IsEligible/Reasons
    issues: pd.DataFrame    # one row per issue type found
    summary: dict

    @property
    def accepted(self) -> pd.DataFrame:
        return self.data[self.data["Status"] == "ACCEPTED"]

    @property
    def flagged(self) -> pd.DataFrame:
        return self.data[self.data["Status"] == "FLAGGED"]

    @property
    def rejected(self) -> pd.DataFrame:
        return self.data[self.data["Status"] == "REJECTED"]

    @property
    def eligible(self) -> pd.DataFrame:
        return self.data[self.data["IsEligible"]]


def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype("string").str.strip() == "")


def run_quality_checks(df: pd.DataFrame) -> QualityResult:
    """Apply all rules to a DataFrame produced by data_loader.load_file."""
    out = df.copy()

    # Parsed (typed) copies; originals stay untouched for review.
    out["QuantityValue"] = pd.to_numeric(out["Quantity"], errors="coerce")
    out["UnitPriceValue"] = pd.to_numeric(out["UnitPrice"], errors="coerce")
    # format="mixed" parses each value on its own, so one odd value cannot
    # cause the rest of the column to fail. Ambiguous dates such as 01/02/2025
    # are read month-first.
    out["InvoiceDateValue"] = pd.to_datetime(out["InvoiceDate"], errors="coerce", format="mixed")
    out["LineRevenue"] = out["QuantityValue"] * out["UnitPriceValue"]

    invoice = out["InvoiceNo"].astype("string")
    is_cancel = invoice.str.upper().str.startswith(config.CANCELLATION_PREFIX.upper()).fillna(False).astype(bool)
    qty_ok = out["QuantityValue"].notna()
    price_ok = out["UnitPriceValue"].notna()

    original_cols = [c for c in config.ALL_COLUMNS]
    masks = {
        "MISSING_INVOICE": _blank(out["InvoiceNo"]),
        "INVALID_DATE": out["InvoiceDateValue"].isna(),
        "INVALID_QUANTITY": ~qty_ok,
        "INVALID_PRICE": ~price_ok,
        "CANCELLATION": is_cancel,
        "NON_POSITIVE_QUANTITY": qty_ok & (out["QuantityValue"] <= 0) & ~is_cancel,
        "NON_POSITIVE_PRICE": price_ok & (out["UnitPriceValue"] <= 0),
        "DUPLICATE_ROW": out[original_cols].duplicated(keep="first"),
        "MISSING_CUSTOMER_ID": _blank(out["CustomerID"]),
        "MISSING_DESCRIPTION": _blank(out["Description"]),
        "MISSING_COUNTRY": _blank(out["Country"]),
    }

    # Row status
    rejected = pd.Series(False, index=out.index)
    flagged = pd.Series(False, index=out.index)
    for name, (_, _, effect, _) in RULES.items():
        if effect == "reject":
            rejected |= masks[name]
        elif effect == "flag":
            flagged |= masks[name]
    flagged &= ~rejected

    out["Status"] = "ACCEPTED"
    out.loc[flagged, "Status"] = "FLAGGED"
    out.loc[rejected, "Status"] = "REJECTED"

    out["IsEligible"] = (
        ~rejected & ~is_cancel & qty_ok & price_ok
        & (out["QuantityValue"] > 0) & (out["UnitPriceValue"] > 0)
    )

    # Row-level reasons, e.g. "CANCELLATION;MISSING_CUSTOMER_ID"
    reasons = pd.Series("", index=out.index)
    for name, mask in masks.items():
        reasons[mask] = reasons[mask] + name + ";"
    out["Reasons"] = reasons.str.rstrip(";")

    # Issue summary (matches DataQualityIssues table)
    records = []
    for name, (column, severity, _, details) in RULES.items():
        count = int(masks[name].sum())
        if count:
            records.append({"ColumnName": column, "IssueType": name,
                            "Severity": severity, "IssueCount": count, "Details": details})
    issues = pd.DataFrame(records, columns=["ColumnName", "IssueType", "Severity", "IssueCount", "Details"])
    order = {s: i for i, s in enumerate(reversed(config.SEVERITIES))}  # ERROR first
    if not issues.empty:
        issues = issues.sort_values(["Severity", "IssueCount"], key=lambda c: c.map(order) if c.name == "Severity" else -c)
        issues = issues.reset_index(drop=True)

    n = len(out)
    n_rej = int(rejected.sum())
    summary = {
        "original_rows": n,
        "accepted_rows": int((out["Status"] == "ACCEPTED").sum()),
        "flagged_rows": int(flagged.sum()),
        "rejected_rows": n_rej,
        "eligible_rows": int(out["IsEligible"].sum()),
        # Flagged rows count as accepted (they are kept); only rejected rows do not.
        "acceptance_rate": round(100 * (n - n_rej) / n, 2) if n else 0.0,
        "error_issue_count": int(issues.loc[issues["Severity"] == "ERROR", "IssueCount"].sum()) if not issues.empty else 0,
        "can_analyze": bool(out["IsEligible"].any()),
    }
    return QualityResult(data=out, issues=issues, summary=summary)