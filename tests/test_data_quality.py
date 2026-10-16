import pandas as pd
import pytest

from src.data_loader import load_file
from src.data_quality import run_quality_checks

COLS = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
        "UnitPrice", "CustomerID", "Country"]


def make_df(rows):
    df = pd.DataFrame(rows, columns=COLS)
    df.insert(0, "SourceRow", range(1, len(df) + 1))
    return df


GOOD = ["1001", "P1", "MUG", "2", "2025-03-01 10:00:00", "5.0", "C100", "France"]


def row(**changes):
    r = dict(zip(COLS, GOOD))
    r.update(changes)
    return [r[c] for c in COLS]


def status_of(rows):
    return run_quality_checks(make_df(rows)).data.iloc[0]


def test_good_row_is_accepted_and_eligible():
    r = status_of([GOOD])
    assert r["Status"] == "ACCEPTED" and r["IsEligible"] and r["LineRevenue"] == 10.0


@pytest.mark.parametrize("change,reason", [
    ({"InvoiceNo": None}, "MISSING_INVOICE"),
    ({"InvoiceDate": "not a date"}, "INVALID_DATE"),
    ({"InvoiceDate": "2025-02-30 09:00:00"}, "INVALID_DATE"),
    ({"InvoiceDate": None}, "INVALID_DATE"),
    ({"UnitPrice": "abc"}, "INVALID_PRICE"),
    ({"UnitPrice": "N/A"}, "INVALID_PRICE"),
    ({"Quantity": "two"}, "INVALID_QUANTITY"),
])
def test_invalid_values_are_rejected(change, reason):
    r = status_of([row(**change)])
    assert r["Status"] == "REJECTED"
    assert reason in r["Reasons"]
    assert not r["IsEligible"]


def test_cancellation_is_flagged_and_excluded():
    r = status_of([row(InvoiceNo="C1001", Quantity="-2")])
    assert r["Status"] == "FLAGGED" and not r["IsEligible"]
    assert "CANCELLATION" in r["Reasons"]
    assert "NON_POSITIVE_QUANTITY" not in r["Reasons"]  # not double-counted


@pytest.mark.parametrize("change,reason", [
    ({"Quantity": "0"}, "NON_POSITIVE_QUANTITY"),
    ({"Quantity": "-3"}, "NON_POSITIVE_QUANTITY"),
    ({"UnitPrice": "-4.5"}, "NON_POSITIVE_PRICE"),
    ({"UnitPrice": "0"}, "NON_POSITIVE_PRICE"),
])
def test_non_positive_values_are_flagged_and_excluded(change, reason):
    r = status_of([row(**change)])
    assert r["Status"] == "FLAGGED" and not r["IsEligible"]
    assert reason in r["Reasons"]


def test_duplicates_are_flagged_not_deleted():
    res = run_quality_checks(make_df([GOOD, GOOD, GOOD]))
    assert len(res.data) == 3                       # nothing dropped
    assert list(res.data["Status"]) == ["ACCEPTED", "FLAGGED", "FLAGGED"]
    assert res.issues.set_index("IssueType").loc["DUPLICATE_ROW", "IssueCount"] == 2


def test_missing_customer_is_warning_but_still_counted():
    res = run_quality_checks(make_df([row(CustomerID=None)]))
    r = res.data.iloc[0]
    assert r["Status"] == "ACCEPTED" and r["IsEligible"]
    issue = res.issues.set_index("IssueType").loc["MISSING_CUSTOMER_ID"]
    assert issue["Severity"] == "WARNING"


def test_rejected_row_not_also_flagged():
    r = status_of([row(InvoiceDate="bad", Quantity="0")])
    assert r["Status"] == "REJECTED"


def test_counts_add_up_and_order_preserved():
    rows = [GOOD, row(InvoiceNo="C9", Quantity="-1"), row(UnitPrice="abc"), GOOD]
    res = run_quality_checks(make_df(rows))
    s = res.summary
    assert s["accepted_rows"] + s["flagged_rows"] + s["rejected_rows"] == s["original_rows"] == 4
    assert list(res.data["SourceRow"]) == [1, 2, 3, 4]
    assert s["acceptance_rate"] == 75.0             # 1 rejected of 4
    assert s["eligible_rows"] == 1 + 1              # the two GOOD rows (one is a duplicate, still eligible)


def test_all_rejected_cannot_analyze():
    res = run_quality_checks(make_df([row(UnitPrice="abc")]))
    assert res.summary["can_analyze"] is False


def test_odd_first_date_does_not_break_other_dates():
    rows = [row(InvoiceDate="garbage"), row(InvoiceNo="1002"), row(InvoiceNo="1003")]
    res = run_quality_checks(make_df(rows))
    assert list(res.data["Status"]) == ["REJECTED", "ACCEPTED", "ACCEPTED"]


def test_sample_file_end_to_end():
    res = run_quality_checks(load_file("data/sample_retail_transactions.csv"))
    s = res.summary
    assert s["original_rows"] == 4594
    assert s["accepted_rows"] + s["flagged_rows"] + s["rejected_rows"] == 4594
    assert s["rejected_rows"] > 0 and s["flagged_rows"] > 0
    types = set(res.issues["IssueType"])
    assert {"INVALID_DATE", "INVALID_PRICE", "CANCELLATION", "DUPLICATE_ROW",
            "MISSING_CUSTOMER_ID"} <= types