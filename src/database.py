"""SQL Server persistence and the SQL side of KPI reconciliation.

- save_run():      stores one processing run (metadata, validated rows, issues)
                   in a single transaction, so a failed load leaves nothing behind.
- run_sql_kpis():  runs the queries in sql/kpi_queries.sql for a RunID.
- reconcile():     compares Python KPIs with SQL KPIs.

All SQL uses bound parameters. Error messages never include the connection
string or credentials.
"""
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Integer, MetaData,
                        Numeric, String, Table, create_engine, desc, insert,
                        inspect, select, text)
from sqlalchemy.exc import SQLAlchemyError

from src import config
from src.data_quality import QualityResult

# Table definitions mirror sql/create_tables.sql (which is what actually creates
# the SQL Server tables). They let us insert safely with bound parameters.
metadata = MetaData()

dataset_runs = Table(
    "DatasetRuns", metadata,
    Column("RunID", Integer, primary_key=True, autoincrement=True),
    Column("FileName", String(260), nullable=False),
    Column("FileHash", String(64)),
    Column("UploadedAt", DateTime, nullable=False),
    Column("OriginalRowCount", Integer, nullable=False),
    Column("AcceptedRowCount", Integer, nullable=False),
    Column("FlaggedRowCount", Integer, nullable=False),
    Column("RejectedRowCount", Integer, nullable=False),
    Column("Status", String(30), nullable=False),
)

sales_transactions = Table(
    "SalesTransactions", metadata,
    Column("TransactionID", BigInteger().with_variant(Integer, "sqlite"),
           primary_key=True, autoincrement=True),
    Column("RunID", Integer, nullable=False),
    Column("SourceRow", Integer, nullable=False),
    Column("InvoiceNo", String(50), nullable=False),
    Column("StockCode", String(50)),
    Column("Description", String(255)),
    Column("Quantity", Integer, nullable=False),
    Column("InvoiceDate", DateTime, nullable=False),
    Column("UnitPrice", Numeric(18, 4), nullable=False),
    Column("CustomerID", String(50)),
    Column("Country", String(100)),
    Column("QualityStatus", String(10), nullable=False),
    Column("IsEligible", Boolean, nullable=False),
)

quality_issues = Table(
    "DataQualityIssues", metadata,
    Column("IssueID", Integer, primary_key=True, autoincrement=True),
    Column("RunID", Integer, nullable=False),
    Column("ColumnName", String(100), nullable=False),
    Column("IssueType", String(50), nullable=False),
    Column("Severity", String(10), nullable=False),
    Column("IssueCount", Integer, nullable=False),
    Column("Details", String(500)),
)

REQUIRED_TABLES = ["DatasetRuns", "SalesTransactions", "DataQualityIssues"]
CHUNK = 5000


class DatabaseError(Exception):
    """A database problem described in words that are safe to show to the user."""


def _safe_message(exc: Exception) -> str:
    # Use only the driver's own message (never the SQLAlchemy URL or statement).
    driver_msg = str(getattr(exc, "orig", "") or type(exc).__name__)
    return ("Database operation failed. Check that SQL Server is running and that "
            "sql/create_tables.sql has been run in SSMS. Details: " + driver_msg[:300])


# ---------------------------------------------------------------- connection
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(config.get_db_url(), fast_executemany=True)
    return _engine


def check_schema(engine=None) -> None:
    """Raise DatabaseError if the server is unreachable or tables are missing."""
    engine = engine or get_engine()
    try:
        existing = set(inspect(engine).get_table_names())
    except SQLAlchemyError as exc:
        raise DatabaseError(_safe_message(exc)) from None
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        raise DatabaseError("Missing table(s): " + ", ".join(missing)
                            + ". Run sql/create_tables.sql in SSMS first.")


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- saving
def _text_or_none(s: pd.Series) -> pd.Series:
    s = s.astype(object)
    return s.where(s.notna() & (s.astype(str).str.strip() != ""), None)


def _records(frame: pd.DataFrame) -> list[dict]:
    frame = frame.astype(object).where(frame.notna(), None)
    return frame.to_dict("records")


def save_run(file_name: str, result: QualityResult, file_hash: str | None = None,
             engine=None) -> int:
    """Store a run and return its RunID.

    Stores accepted and flagged rows (rejected rows are not stored; they stay
    available as a download). If file_hash matches an earlier run, that run's ID
    is returned and nothing is inserted, so re-uploading a file does not
    duplicate data. The whole load is one transaction.
    """
    engine = engine or get_engine()
    # reset_index: rejected rows leave gaps in the index, and every column below
    # must line up by position, not by the old row labels.
    stored = result.data[result.data["Status"] != "REJECTED"].reset_index(drop=True)
    if stored.empty:
        raise DatabaseError("Nothing to store: every row was rejected.")
    if not (stored["QuantityValue"] % 1 == 0).all():
        raise DatabaseError("Quantity contains non-whole numbers; the SalesTransactions "
                            "table stores whole units only.")

    s = result.summary
    try:
        with engine.begin() as conn:
            if file_hash:
                existing = conn.execute(
                    select(dataset_runs.c.RunID)
                    .where(dataset_runs.c.FileHash == file_hash)
                    .order_by(desc(dataset_runs.c.RunID))
                ).scalar()
                if existing is not None:
                    return int(existing)

            run_id = conn.execute(insert(dataset_runs).values(
                FileName=file_name[:260],
                FileHash=file_hash,
                UploadedAt=datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0),
                OriginalRowCount=s["original_rows"],
                AcceptedRowCount=s["accepted_rows"],
                FlaggedRowCount=s["flagged_rows"],
                RejectedRowCount=s["rejected_rows"],
                Status="LOADED",
            )).inserted_primary_key[0]

            rows = pd.DataFrame({
                "RunID": run_id,
                "SourceRow": stored["SourceRow"].astype(int),
                "InvoiceNo": _text_or_none(stored["InvoiceNo"]),
                "StockCode": _text_or_none(stored["StockCode"]),
                "Description": _text_or_none(stored["Description"]),
                "Quantity": stored["QuantityValue"].astype(int),
                "InvoiceDate": [d.to_pydatetime() for d in stored["InvoiceDateValue"]],
                "UnitPrice": stored["UnitPriceValue"].astype(float),
                "CustomerID": _text_or_none(stored["CustomerID"]),
                "Country": _text_or_none(stored["Country"]),
                "QualityStatus": stored["Status"],
                "IsEligible": stored["IsEligible"].astype(bool),
            })
            recs = _records(rows)
            for i in range(0, len(recs), CHUNK):
                conn.execute(insert(sales_transactions), recs[i:i + CHUNK])

            if not result.issues.empty:
                issues = result.issues.copy()
                issues.insert(0, "RunID", run_id)
                conn.execute(insert(quality_issues), _records(issues))
            return int(run_id)
    except SQLAlchemyError as exc:
        raise DatabaseError(_safe_message(exc)) from None


# ---------------------------------------------------------------- SQL KPIs
def load_queries() -> dict[str, str]:
    """Read sql/kpi_queries.sql into {name: sql}, with @RunID bound as :run_id."""
    raw = (config.BASE_DIR / "sql" / "kpi_queries.sql").read_text(encoding="utf-8")
    parts = re.split(r"^--\s*name:\s*(\w+)\s*$", raw, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].replace("@RunID", ":run_id").strip()
            for i in range(1, len(parts) - 1, 2)}


def _num(value):
    if value is None or pd.isna(value):
        return None
    return float(value) if isinstance(value, (Decimal, float)) else int(value)


def run_sql_kpis(run_id: int, engine=None) -> dict:
    """Run the SQL KPI queries for one run."""
    engine = engine or get_engine()
    queries = load_queries()
    try:
        with engine.connect() as conn:
            def one(name):
                return _num(conn.execute(text(queries[name]), {"run_id": run_id}).scalar())

            def table(name):
                df = pd.read_sql_query(text(queries[name]), conn, params={"run_id": run_id})
                for col in ("Revenue",):
                    if col in df:
                        df[col] = df[col].astype(float)
                return df

            return {
                "Total revenue": one("total_revenue"),
                "Distinct orders": one("distinct_orders"),
                "Average order value": one("average_order_value"),
                "Unique customers": one("unique_customers"),
                "monthly": table("monthly_revenue"),
                "countries": table("country_revenue"),
            }
    except SQLAlchemyError as exc:
        raise DatabaseError(_safe_message(exc)) from None


# ---------------------------------------------------------------- reconciliation
def reconcile(py_kpis: dict, sql_kpis: dict, tolerance: float = 0.01) -> dict:
    """Compare Python and SQL results.

    Money values must agree within `tolerance`; counts must match exactly.
    Returns {"ok": bool, "checks": DataFrame, "monthly_mismatches": DataFrame}.
    """
    py = py_kpis["values"]
    checks = []

    def add(name, a, b, money):
        if a is None or b is None:
            match = a is None and b is None
            diff = None
        else:
            diff = round(float(a) - float(b), 4)
            match = abs(diff) <= tolerance if money else diff == 0
        checks.append({"Check": name, "Python": a, "SQL": b, "Difference": diff, "Match": bool(match)})

    add("Total revenue", py["Total revenue"], sql_kpis["Total revenue"], True)
    add("Distinct orders", py["Distinct orders"], sql_kpis["Distinct orders"], False)
    add("Average order value", py["Average order value"], sql_kpis["Average order value"], True)
    add("Unique customers", py["Unique customers"], sql_kpis["Unique customers"], False)

    m = py_kpis["monthly"].merge(sql_kpis["monthly"], on="Month", how="outer",
                                 suffixes=("_py", "_sql")).sort_values("Month")
    rev_ok = (m["Revenue_py"] - m["Revenue_sql"]).abs() <= tolerance      # NaN -> False
    ord_ok = m["Orders_py"] == m["Orders_sql"]
    mismatches = m[~(rev_ok & ord_ok)].reset_index(drop=True)
    checks.append({"Check": f"Monthly revenue and orders ({len(m)} months)",
                   "Python": None, "SQL": None, "Difference": None,
                   "Match": bool(mismatches.empty)})

    table = pd.DataFrame(checks)
    return {"ok": bool(table["Match"].all()), "checks": table, "monthly_mismatches": mismatches}