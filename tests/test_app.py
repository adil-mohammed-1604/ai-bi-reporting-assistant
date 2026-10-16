"""Smoke tests for the Streamlit pages, using Streamlit's AppTest runner."""
import pytest
from streamlit.testing.v1 import AppTest

from src import config
from src.data_loader import LoaderError
from src.ui_helpers import SAMPLE_PATH, process

TIMEOUT = 60
APP = str(config.BASE_DIR / "app.py")
QUALITY_PAGE = str(config.BASE_DIR / "pages" / "1_Data_Quality.py")
DASHBOARD_PAGE = str(config.BASE_DIR / "pages" / "2_Analytics_Dashboard.py")
AI_PAGE = str(config.BASE_DIR / "pages" / "3_AI_Report.py")


def metric_values(at):
    return {m.label: m.value for m in at.metric}


@pytest.fixture(scope="module")
def sample_upload():
    return process(SAMPLE_PATH.read_bytes(), SAMPLE_PATH.name)


def test_home_before_upload_shows_guidance():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert not at.exception
    assert any("Use sample dataset" in b.label for b in at.button)
    assert any("Upload a file" in i.value for i in at.info)


def test_home_with_sample_dataset():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    at.button(key="load_sample").click().run()
    assert not at.exception
    m = metric_values(at)
    assert m["Rows"] == "4,594"
    assert m["Accepted"] == "4,436" and m["Flagged for review"] == "149" and m["Rejected"] == "9"
    assert m["Acceptance rate"] == "99.8%"
    assert m["Exact duplicate rows"] == "15"


def test_database_failure_is_reported_not_crashed(monkeypatch):
    """Without SQL Server the page must show a clear error and keep working."""
    from src import database

    def boom(*a, **k):
        raise database.DatabaseError("simulated: server not reachable")
    monkeypatch.setattr(database, "check_schema", boom)

    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    at.button(key="load_sample").click().run()
    at.button(key="save_db").click().run()
    assert not at.exception
    assert any("database step failed" in e.value for e in at.error)
    assert metric_values(at)["Rows"] == "4,594"      # rest of the page still works


def test_navigating_from_home_to_quality_page_keeps_the_upload():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    at.button(key="load_sample").click().run()
    at.switch_page("pages/1_Data_Quality.py").run()
    assert not at.exception
    assert metric_values(at)["Original rows"] == "4,594"


def test_quality_page_requires_upload():
    at = AppTest.from_file(QUALITY_PAGE, default_timeout=TIMEOUT).run()
    assert not at.exception
    assert any("No dataset loaded" in i.value for i in at.info)


def test_quality_page_with_data(sample_upload):
    at = AppTest.from_file(QUALITY_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = sample_upload
    at.run()
    assert not at.exception
    m = metric_values(at)
    assert m["Original rows"] == "4,594" and m["Rejected"] == "9" and m["Flagged"] == "149"
    tabs = [t.label for t in at.tabs]
    assert "Rejected (9)" in tabs and "Flagged (149)" in tabs


def test_bad_file_gives_readable_error():
    with pytest.raises(LoaderError, match="Missing required column"):
        process(b"InvoiceNo,Quantity\n1,2\n", "bad.csv")
    with pytest.raises(LoaderError, match="Unsupported file type"):
        process(b"x", "notes.txt")


def test_all_rejected_file_is_handled():
    csv = b"InvoiceNo,StockCode,Quantity,InvoiceDate,UnitPrice\nA,P1,1,not a date,5\n"
    up = process(csv, "all_bad.csv")
    assert up["kpis"] is None and up["quality"].summary["can_analyze"] is False
    at = AppTest.from_file(QUALITY_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = up
    at.run()
    assert not at.exception


# ------------------------------------------------------------------ analytics dashboard
def dashboard(upload):
    at = AppTest.from_file(DASHBOARD_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = upload
    return at.run()


def test_dashboard_requires_upload():
    at = AppTest.from_file(DASHBOARD_PAGE, default_timeout=TIMEOUT).run()
    assert not at.exception and any("No dataset loaded" in i.value for i in at.info)


def test_dashboard_kpis_match_reference_values(sample_upload):
    at = dashboard(sample_upload)
    assert not at.exception
    m = metric_values(at)
    assert m["Total revenue"] == "346,087.77"
    assert m["Distinct orders"] == "1,453"
    assert m["Average order value"] == "238.19"
    assert m["Unique customers"] == "391"
    assert m["Revenue growth (latest month)"] == "-3.85%"
    assert len(at.get("plotly_chart")) == 3


def test_dashboard_country_filter_recalculates(sample_upload):
    at = dashboard(sample_upload)
    at.multiselect(key="country_filter").set_value(["France"]).run()
    assert not at.exception
    assert metric_values(at)["Total revenue"] == "36,749.85"
    assert any("Filtered view" in i.value for i in at.info)


def test_dashboard_month_filter_recalculates(sample_upload):
    at = dashboard(sample_upload)
    at.select_slider(key="month_range").set_value(("2025-01", "2025-03")).run()
    assert not at.exception
    assert metric_values(at)["Total revenue"] == "82,472.33"


def test_dashboard_empty_country_selection_is_handled(sample_upload):
    at = dashboard(sample_upload)
    at.multiselect(key="country_filter").set_value([]).run()
    assert not at.exception and any("at least one country" in w.value for w in at.warning)


def test_dashboard_shows_reconciliation_status(sample_upload):
    import copy
    up = copy.copy(sample_upload)
    up["db"] = {"run_id": 7, "rec": {"ok": True}}
    assert any("reconciled" in s.value for s in dashboard(up).success)
    up["db"] = {"run_id": 7, "rec": {"ok": False}}
    assert any("disagree" in w.value for w in dashboard(up).warning)


def test_dashboard_with_no_eligible_rows(sample_upload):
    csv = b"InvoiceNo,StockCode,Quantity,InvoiceDate,UnitPrice\nA,P1,1,not a date,5\n"
    at = dashboard(process(csv, "all_bad.csv"))
    assert not at.exception and any("No eligible rows" in e.value for e in at.error)


# ------------------------------------------------------------------ AI report page
def ai_page(upload):
    at = AppTest.from_file(AI_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = upload
    return at.run()


def fresh(sample_upload):
    import copy
    up = copy.copy(sample_upload)
    up["db"], up["report"] = None, None
    return up


def test_ai_page_requires_upload():
    at = AppTest.from_file(AI_PAGE, default_timeout=TIMEOUT).run()
    assert not at.exception and any("No dataset loaded" in i.value for i in at.info)


def test_ai_page_without_key_offers_template_only(sample_upload, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    at = ai_page(fresh(sample_upload))
    assert not at.exception
    assert at.button(key="gen_ai").disabled and not at.button(key="gen_template").disabled
    assert any("not set" in m.value for m in at.markdown)


def test_ai_page_template_report(sample_upload, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    at = ai_page(fresh(sample_upload))
    at.button(key="gen_template").click().run()
    assert not at.exception
    assert any("Every number in this draft was traced" in s.value for s in at.success)
    assert any("Draft." in w.value for w in at.warning)
    assert "346,087.77" in " ".join(m.value for m in at.markdown)


def test_ai_page_with_fake_model_and_failures(sample_upload, monkeypatch):
    from src import ai_report
    monkeypatch.setattr(config, "LLM_API_KEY", "fake-key")
    payload = ai_report.build_payload(sample_upload["kpis"], None)

    # good reply
    monkeypatch.setattr(ai_report, "call_llm", lambda s, u: __import__("json").dumps({
        "executive_summary": "Revenue was 346,087.77 across 1,453 orders.",
        "key_findings": ["France was a key market."], "follow_up_analysis": ["Why did December dip?"],
        "limitations": ["Customer counts are a lower bound."]}))
    at = ai_page(fresh(sample_upload))
    at.button(key="gen_ai").click().run()
    assert not at.exception and any("traced" in s.value for s in at.success)

    # invented number -> blocked, text hidden by default
    monkeypatch.setattr(ai_report, "call_llm", lambda s, u: __import__("json").dumps({
        "executive_summary": "Revenue was 999,999.99.", "key_findings": ["a"],
        "follow_up_analysis": [], "limitations": ["b"]}))
    at = ai_page(fresh(sample_upload))
    at.button(key="gen_ai").click().run()
    assert any("Not verified" in e.value and "999,999.99" in e.value for e in at.error)
    assert "999,999.99" not in " ".join(m.value for m in at.markdown)
    assert at.get("download_button")[0].proto.disabled

    # API failure -> clear error, page still works
    def boom(s, u):
        raise ai_report.AIReportError("gemini: Rate limit or quota reached")
    monkeypatch.setattr(ai_report, "call_llm", boom)
    at = ai_page(fresh(sample_upload))
    at.button(key="gen_ai").click().run()
    assert not at.exception and any("could not be produced" in e.value for e in at.error)
    assert not at.button(key="gen_template").disabled


def test_ai_page_blocks_when_python_and_sql_disagree(sample_upload, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "fake-key")
    up = fresh(sample_upload)
    up["db"] = {"run_id": 7, "rec": {"ok": False}}
    at = ai_page(up)
    assert any("Blocked" in e.value for e in at.error)
    assert at.button(key="gen_ai").disabled and at.button(key="gen_template").disabled


# ------------------------------------------------------------------ export center
EXPORT_PAGE = str(config.BASE_DIR / "pages" / "4_Export_Center.py")


def test_export_page_requires_upload():
    at = AppTest.from_file(EXPORT_PAGE, default_timeout=TIMEOUT).run()
    assert not at.exception and any("No dataset loaded" in i.value for i in at.info)


def test_export_page_with_data_and_report(sample_upload):
    from src import ai_report
    up = fresh(sample_upload)
    up["report"] = ai_report.generate_template_report(up["kpis"], None)
    at = AppTest.from_file(EXPORT_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = up
    at.run()
    assert not at.exception
    assert len(at.get("download_button")) == 6          # xlsx + 4 csv + report


def test_export_page_blocks_unverified_report(sample_upload):
    import copy
    up = fresh(sample_upload)
    rep = copy.copy(__import__("src.ai_report", fromlist=["x"]).generate_template_report(up["kpis"], None))
    rep.status, rep.unverified = "UNVERIFIED", ["999"]
    up["report"] = rep
    at = AppTest.from_file(EXPORT_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = up
    at.run()
    assert not at.exception and any("can't be exported" in e.value for e in at.error)


def test_export_page_with_no_eligible_rows():
    up = process(b"InvoiceNo,StockCode,Quantity,InvoiceDate,UnitPrice\nA,P1,1,not a date,5\n", "bad.csv")
    at = AppTest.from_file(EXPORT_PAGE, default_timeout=TIMEOUT)
    at.session_state["upload"] = up
    at.run()
    assert not at.exception