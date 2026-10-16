"""Database tests that need no SQL Server: save_run is exercised against an
in-memory SQLite database, and reconcile() is a pure function. The T-SQL in
sql/kpi_queries.sql is verified separately by running pipeline_check.py
against SQL Server."""
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from src.analytics import compute_kpis
from src.data_quality import run_quality_checks
from src.database import (DatabaseError, check_schema, dataset_runs, load_queries,
                          metadata, quality_issues, reconcile, sales_transactions,
                          save_run)

COLS = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
        "UnitPrice", "CustomerID", "Country"]
ROWS = [
    ["A", "P1", "MUG", "2", "2025-01-05 10:00:00", "5", "C1", "France"],
    ["A", "P2", "LAMP", "1", "2025-01-05 10:00:00", "10", "C1", "France"],
    ["B", "P1", "MUG", "3", "2025-01-20 09:00:00", "4", "C2", "Spain"],
    ["Z", "P3", None, "1", "2025-02-10 12:00:00", "8", None, None],
    ["C9", "P1", "MUG", "-2", "2025-01-06 10:00:00", "5", "C1", "France"],   # cancellation (stored, flagged)
    ["F", "P1", "MUG", "2", "bad date", "5", "C1", "France"],                # rejected (not stored)
]


def make_result(rows=ROWS):
    df = pd.DataFrame(rows, columns=COLS)
    df.insert(0, "SourceRow", range(1, len(df) + 1))
    return run_quality_checks(df)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    metadata.create_all(eng)
    return eng


def count(engine, table):
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(table)).scalar()


# ------------------------------------------------------------ save_run
def test_save_run_stores_accepted_and_flagged_not_rejected(engine):
    run_id = save_run("test.csv", make_result(), engine=engine)
    assert run_id == 1
    assert count(engine, sales_transactions) == 5          # 6 rows - 1 rejected
    with engine.connect() as c:
        run = c.execute(select(dataset_runs)).mappings().one()
        statuses = {r[0] for r in c.execute(select(sales_transactions.c.QualityStatus))}
    assert (run["OriginalRowCount"], run["AcceptedRowCount"],
            run["FlaggedRowCount"], run["RejectedRowCount"]) == (6, 4, 1, 1)
    assert run["Status"] == "LOADED"
    assert statuses == {"ACCEPTED", "FLAGGED"}


def test_rejected_rows_in_the_middle_keep_source_rows_aligned(engine):
    """Regression: gaps in the row index once produced NULL SourceRow values."""
    rows = [
        ["A", "P1", "MUG", "2", "2025-01-05 10:00:00", "5", "C1", "France"],
        ["F", "P1", "MUG", "2", "bad date", "5", "C1", "France"],       # rejected, source row 2
        ["B", "P1", "MUG", "3", "2025-01-20 09:00:00", "4", "C2", "Spain"],
        ["G", "P1", "MUG", "2", "bad date", "5", "C1", "France"],       # rejected, source row 4
        ["Z", "P3", None, "1", "2025-02-10 12:00:00", "8", None, None],
    ]
    save_run("t.csv", make_result(rows), engine=engine)
    with engine.connect() as c:
        got = c.execute(select(sales_transactions.c.SourceRow, sales_transactions.c.InvoiceNo,
                               sales_transactions.c.InvoiceDate)
                        .order_by(sales_transactions.c.SourceRow)).all()
    assert [(r[0], r[1]) for r in got] == [(1, "A"), (3, "B"), (5, "Z")]
    assert got[1][2].isoformat() == "2025-01-20T09:00:00"


def test_missing_values_stored_as_null(engine):
    save_run("t.csv", make_result(), engine=engine)
    with engine.connect() as c:
        row = c.execute(select(sales_transactions).where(sales_transactions.c.InvoiceNo == "Z")).mappings().one()
    assert row["CustomerID"] is None and row["Country"] is None and row["Description"] is None
    assert row["SourceRow"] == 4


def test_issues_saved(engine):
    save_run("t.csv", make_result(), engine=engine)
    with engine.connect() as c:
        types = {r[0] for r in c.execute(select(quality_issues.c.IssueType))}
    assert {"INVALID_DATE", "CANCELLATION", "MISSING_CUSTOMER_ID"} <= types


def test_same_file_hash_does_not_duplicate(engine):
    first = save_run("t.csv", make_result(), file_hash="abc", engine=engine)
    again = save_run("t.csv", make_result(), file_hash="abc", engine=engine)
    assert first == again
    assert count(engine, dataset_runs) == 1 and count(engine, sales_transactions) == 5


def test_different_hash_creates_new_run(engine):
    a = save_run("t.csv", make_result(), file_hash="abc", engine=engine)
    b = save_run("t.csv", make_result(), file_hash="def", engine=engine)
    assert b == a + 1


def test_all_rejected_raises(engine):
    bad = make_result([["A", "P1", "MUG", "1", "bad", "5", "C1", "France"]])
    with pytest.raises(DatabaseError):
        save_run("t.csv", bad, engine=engine)
    assert count(engine, dataset_runs) == 0


def test_fractional_quantity_raises_and_stores_nothing(engine):
    res = make_result([["A", "P1", "MUG", "2.5", "2025-01-05 10:00:00", "5", "C1", "France"]])
    with pytest.raises(DatabaseError):
        save_run("t.csv", res, engine=engine)
    assert count(engine, dataset_runs) == 0


def test_failed_load_rolls_back_everything(engine):
    # Break the issues table so the last insert fails; nothing may remain.
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE "DataQualityIssues"')
    with pytest.raises(DatabaseError):
        save_run("t.csv", make_result(), engine=engine)
    assert count(engine, dataset_runs) == 0 and count(engine, sales_transactions) == 0


def test_check_schema(engine):
    check_schema(engine)
    empty = create_engine("sqlite://", poolclass=StaticPool)
    with pytest.raises(DatabaseError, match="create_tables.sql"):
        check_schema(empty)


# ------------------------------------------------------------ query file
def test_queries_load_with_bound_parameter():
    q = load_queries()
    assert set(q) == {"total_revenue", "distinct_orders", "average_order_value",
                      "unique_customers", "monthly_revenue", "country_revenue"}
    for name, sql in q.items():
        assert ":run_id" in sql and "@RunID" not in sql, name
        assert "NOT LIKE 'C%'" in sql and "Quantity > 0" in sql and "UnitPrice > 0" in sql, name


# ------------------------------------------------------------ reconcile
def sql_like(py, **overrides):
    out = {"Total revenue": py["values"]["Total revenue"],
           "Distinct orders": py["values"]["Distinct orders"],
           "Average order value": py["values"]["Average order value"],
           "Unique customers": py["values"]["Unique customers"],
           "monthly": py["monthly"].copy()}
    out.update(overrides)
    return out


def test_reconcile_agrees():
    py = compute_kpis(make_result())
    r = reconcile(py, sql_like(py))
    assert r["ok"] and r["checks"]["Match"].all() and r["monthly_mismatches"].empty


def test_reconcile_allows_rounding_but_catches_real_differences():
    py = compute_kpis(make_result())
    assert reconcile(py, sql_like(py, **{"Total revenue": py["values"]["Total revenue"] + 0.004}))["ok"]
    bad = reconcile(py, sql_like(py, **{"Total revenue": py["values"]["Total revenue"] + 0.5}))
    assert not bad["ok"]
    assert not bad["checks"].set_index("Check").loc["Total revenue", "Match"]


def test_reconcile_counts_must_match_exactly():
    py = compute_kpis(make_result())
    assert not reconcile(py, sql_like(py, **{"Distinct orders": py["values"]["Distinct orders"] + 1}))["ok"]


def test_reconcile_detects_monthly_and_missing_month():
    py = compute_kpis(make_result())
    changed = py["monthly"].copy()
    changed.loc[0, "Revenue"] += 5
    r = reconcile(py, sql_like(py, monthly=changed))
    assert not r["ok"] and len(r["monthly_mismatches"]) == 1
    r2 = reconcile(py, sql_like(py, monthly=py["monthly"].iloc[:1]))
    assert not r2["ok"] and r2["monthly_mismatches"]["Month"].tolist() == ["2025-02"]


def test_reconcile_none_values():
    py = compute_kpis(make_result())
    assert not reconcile(py, sql_like(py, **{"Total revenue": None}))["ok"]