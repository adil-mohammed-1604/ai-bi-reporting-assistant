import pandas as pd
import pytest

from src.analytics import (AnalyticsError, average_order_value, compute_kpis,
                           country_revenue, distinct_orders, monthly_revenue,
                           revenue_growth, top_products, total_revenue,
                           unique_customers)
from src.data_loader import load_file
from src.data_quality import run_quality_checks

COLS = ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
        "UnitPrice", "CustomerID", "Country"]


def make_result(rows):
    df = pd.DataFrame(rows, columns=COLS)
    df.insert(0, "SourceRow", range(1, len(df) + 1))
    return run_quality_checks(df)


# Hand-calculated fixture
#   A (Jan, C1): 2x5 + 1x10 = 20     B (Jan, C2): 3x4 = 12     Z (Feb, no customer): 1x8 = 8
#   (invoice ids must not start with 'C': that prefix means cancellation)
ROWS = [
    ["A", "P1", "MUG", "2", "2025-01-05 10:00:00", "5", "C1", "France"],
    ["A", "P2", "LAMP", "1", "2025-01-05 10:00:00", "10", "C1", "France"],
    ["B", "P1", "MUG", "3", "2025-01-20 09:00:00", "4", "C2", "Spain"],
    ["Z", "P3", None, "1", "2025-02-10 12:00:00", "8", None, None],
]


@pytest.fixture
def elig():
    return make_result(ROWS).eligible


def test_total_revenue(elig):
    assert total_revenue(elig) == 40.0


def test_distinct_orders_counts_invoices_not_rows(elig):
    assert len(elig) == 4 and distinct_orders(elig) == 3


def test_average_order_value_is_order_level(elig):
    assert average_order_value(elig) == pytest.approx(13.33, abs=0.01)   # 40 / 3
    assert average_order_value(elig) != pytest.approx(40 / 4)            # not row-level (10.0)


def test_unique_customers_ignores_missing(elig):
    assert unique_customers(elig) == 2


def test_monthly_revenue(elig):
    m = monthly_revenue(elig)
    assert list(m["Month"]) == ["2025-01", "2025-02"]
    assert list(m["Revenue"]) == [32.0, 8.0]
    assert list(m["Orders"]) == [2, 1]


def test_revenue_growth_and_edge_cases():
    assert revenue_growth(8, 32) == -75.0
    assert revenue_growth(10, 0) is None
    assert revenue_growth(10, None) is None
    assert revenue_growth(10, float("nan")) is None


def test_country_and_product_tables(elig):
    c = country_revenue(elig).set_index("Country")["Revenue"]
    assert c["France"] == 20.0 and c["Spain"] == 12.0 and c["Unknown"] == 8.0
    p = top_products(elig).set_index("StockCode")
    assert p.loc["P1", "Revenue"] == 22.0 and p.loc["P1", "UnitsSold"] == 5


def test_compute_kpis_structure_and_values():
    k = compute_kpis(make_result(ROWS))
    assert k["period"] == "2025-01-05 to 2025-02-10"
    assert k["values"]["Total revenue"] == 40.0
    assert k["values"]["Distinct orders"] == 3
    assert k["values"]["Revenue growth % (latest month vs previous)"] == -75.0
    for m in k["metrics"]:
        assert set(m) == {"name", "value", "period", "definition", "limitations"}


def test_excluded_rows_do_not_affect_kpis():
    noisy = ROWS + [
        ["C99", "P1", "MUG", "-2", "2025-01-06 10:00:00", "5", "C1", "France"],   # cancellation
        ["D", "P1", "MUG", "0", "2025-01-06 10:00:00", "5", "C1", "France"],      # zero qty
        ["E", "P1", "MUG", "2", "2025-01-06 10:00:00", "-5", "C1", "France"],     # negative price
        ["F", "P1", "MUG", "2", "bad date", "5", "C1", "France"],                 # rejected
    ]
    k = compute_kpis(make_result(noisy))
    assert k["values"]["Total revenue"] == 40.0
    assert k["values"]["Distinct orders"] == 3
    assert k["exclusions"]["excluded_rows"] == 4


def test_no_eligible_rows_raises():
    with pytest.raises(AnalyticsError):
        compute_kpis(make_result([["A", "P1", "MUG", "1", "bad", "5", "C1", "France"]]))


def test_single_month_growth_is_none():
    k = compute_kpis(make_result(ROWS[:3]))
    assert k["values"]["Revenue growth % (latest month vs previous)"] is None


def test_sample_file_consistency():
    k = compute_kpis(run_quality_checks(load_file("data/sample_retail_transactions.csv")))
    v = k["values"]
    assert v["Average order value"] * v["Distinct orders"] == pytest.approx(v["Total revenue"], abs=v["Distinct orders"] * 0.005 + 0.01)
    assert k["monthly"]["Revenue"].sum() == pytest.approx(v["Total revenue"], abs=0.05)
    assert k["countries"]["Revenue"].sum() == pytest.approx(v["Total revenue"], abs=0.05)
    assert len(k["monthly"]) == 12


def test_unique_customers_limitation_only_mentions_lower_bound_when_ids_are_missing():
    from src.data_loader import load_file
    from src.data_quality import run_quality_checks
    from src.analytics import compute_kpis
    from src import config
    clean = config.BASE_DIR / "data" / "test_files" / "test1_clean.csv"
    messy = config.BASE_DIR / "data" / "test_files" / "test2_messy.csv"
    def note(path):
        k = compute_kpis(run_quality_checks(load_file(path)))
        return next(m for m in k["metrics"] if m["name"] == "Unique customers")["limitations"]
    assert "lower bound" not in note(clean)
    assert "1 eligible rows have no CustomerID" in note(messy)