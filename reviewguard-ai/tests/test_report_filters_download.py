"""Offline AppTest verification of saved-report filters and guarded downloads."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.reports.builder import build_review_report
from reviewguard.reports.export import export_report_json
from reviewguard.reports.models import ReviewReport
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding

APP = Path(__file__).resolve().parents[1] / "app.py"
SOURCE = "# FULL_UPLOAD_SENTINEL\ndef example(value):\n    return value\n"


class Upload(BytesIO):
    def __init__(self, name="example.py", source=SOURCE):
        super().__init__(source.encode())
        self.name, self.size = name, len(source.encode())


def report(severities=("LOW", "HIGH", "CRITICAL", "MEDIUM", "HIGH"), partial=False):
    findings = [ReviewFinding(finding_id=f"q-{i}", agent="code_quality", title=f"Concern {i}",
        category="logic", severity=severity, filename="example.py", line_number=3,
        description=f"Synthetic concern {i}.", evidence="    return value",
        recommendation="Validate behavior.", confidence=0.5 + i * 0.05,
        suggested_tests=["test_value: input=1; expected=1"])
        for i, severity in enumerate(severities)]
    results = {agent: AgentReviewResult(agent=agent, status="failed" if partial and agent == AgentType.security else "success",
        findings=findings if agent == AgentType.code_quality else [],
        error_message="RAW_PRIVATE_PROVIDER_BODY" if partial and agent == AgentType.security else None)
        for agent in AgentType}
    return build_review_report(aggregate_findings(results, sources={"example.py": SOURCE}), filename="example.py")


@pytest.fixture(autouse=True)
def offline():
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as send:
        yield
    send.assert_not_called()


@pytest.mark.parametrize("selection", ["All", "Critical", "High", "Medium", "Low"])
def test_filter_uses_saved_priority_order_and_full_summary(selection):
    value = report(partial=True)
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=value) as service:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        assert app.selectbox(key="severity_filter").value == "All"
        original_counts = [(item.label, item.value) for item in app.metric]
        app.selectbox(key="severity_filter").select(selection).run()
        assert not app.exception
        expected = [group.representative for group in value.findings if selection == "All" or group.representative.severity.value == selection.upper()]
        titles = [item.value for item in app.text if item.value.startswith("Title: ")]
        assert titles == [f"Title: {item.title}" for item in expected]
        assert len(app.expander) == len(expected)
        assert [(item.label, item.value) for item in app.metric] == original_counts
        assert original_counts == [("CRITICAL", "1"), ("HIGH", "2"), ("MEDIUM", "1"), ("LOW", "1")]
        assert f"Visible findings: {len(expected)} of 5" in [item.value for item in app.caption]
        assert app.warning[0].value == "Review status: partial"
        assert any("agents failed" in item.value for item in app.warning)
        assert "Security Reviewer: failed" in " ".join(item.value for item in app.markdown)
        assert app.session_state.review_report == value
        app.run()
        service.assert_called_once()


def test_empty_filter_has_helpful_notice_and_counts_stay_complete():
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report(("HIGH",))):
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        app.selectbox(key="severity_filter").select("Low").run()
    assert not app.exception and not app.expander
    assert any("No findings match Low" in item.value for item in app.info)
    assert "Visible findings: 0 of 1" in [item.value for item in app.caption]
    assert next(item for item in app.metric if item.label == "HIGH").value == "1"
    assert not app.get("download_button")[0].proto.disabled


def test_download_data_is_full_guarded_json_without_rerun_or_review(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "FAKE_FILTER_DOWNLOAD_KEY")
    value = report(partial=True)
    original_download = st.download_button
    with patch("streamlit.file_uploader", return_value=Upload()), \
         patch("reviewguard.ui.review_service.run_review", return_value=value) as service, \
         patch("streamlit.download_button", wraps=original_download) as download:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        app.selectbox(key="severity_filter").select("Low").run()
        options = download.call_args.kwargs
        assert options["data"] == export_report_json(value)
        assert options["mime"] == "application/json"
        assert options["file_name"] == "reviewguard-report.json"
        assert options["on_click"] == "ignore"
        assert not app.get("download_button")[0].proto.disabled
        assert app.get("download_button")[0].proto.ignore_rerun
        decoded = ReviewReport.model_validate_json(options["data"])
        assert decoded == value and decoded.total_unique_findings == 5
        for prohibited in ("FAKE_FILTER_DOWNLOAD_KEY", "RAW_PRIVATE_PROVIDER_BODY", "FULL_UPLOAD_SENTINEL", "source_code"):
            assert prohibited not in options["data"]
        app.run()  # Even an ordinary browser-triggered rerun cannot submit again.
        service.assert_called_once()


def test_export_rejection_offers_no_download_or_fallback(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "FAKE_EXPORT_REJECTED_SECRET")
    value = report()
    value.findings[0].representative.recommendation = "FAKE_EXPORT_REJECTED_SECRET"
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=value):
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
    assert not app.exception
    assert "potentially sensitive content" in app.error[0].value
    assert not app.get("download_button") and not app.expander
    assert "FAKE_EXPORT_REJECTED_SECRET" not in " ".join(item.value for item in [*app.error, *app.text, *app.markdown])


def test_new_upload_clears_download_report_and_resets_filter():
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report()) as service:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        app.selectbox(key="severity_filter").select("High").run()
        with patch("streamlit.file_uploader", return_value=Upload("changed.py")):
            app.run()
        assert not app.exception and app.session_state.review_report is None
        assert not app.selectbox
        assert app.get("download_button")[0].proto.disabled
        service.assert_called_once()


def test_no_report_download_disabled():
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.get("download_button")[0].proto.disabled
    assert not app.selectbox
