"""Offline AppTest coverage of prioritized report rendering and safe text."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.reports.builder import build_review_report
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding

APP = Path(__file__).resolve().parents[1] / "app.py"
SOURCE = "def example(value):\n    return value\n"


class Upload(BytesIO):
    def __init__(self, name="example.py", source=SOURCE):
        super().__init__(source.encode())
        self.name, self.size = name, len(source.encode())


def finding(**changes):
    return ReviewFinding.model_validate(dict({
        "finding_id": "q-1", "agent": "code_quality", "title": "Boundary concern", "category": "logic",
        "severity": "HIGH", "filename": "example.py", "line_number": 2,
        "description": "Check boundary behavior.", "evidence": "    return value",
        "recommendation": "Validate expected behavior.", "confidence": 0.85,
        "suggested_tests": ["test_zero: input=0; expected=0"],
    }, **changes))


def report(findings=(), status="completed"):
    results = {agent: AgentReviewResult(agent=agent, status="failed" if status == "failed" or
        (status == "partial" and agent == AgentType.security) else "success",
        findings=[item for item in findings if item.agent == agent],
        error_message="PRIVATE_PROVIDER_BODY" if status == "failed" or (status == "partial" and agent == AgentType.security) else None)
        for agent in AgentType}
    return build_review_report(aggregate_findings(results, sources={"example.py": SOURCE}), filename="example.py")


@pytest.fixture(autouse=True)
def no_network():
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as send:
        yield
    send.assert_not_called()


def display(value):
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=value):
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
    assert not app.exception
    return app


def test_completed_findings_priority_counts_and_exact_details():
    originals = [finding(), finding(finding_id="q-2", title="Low concern", severity="LOW"),
        finding(agent="security", finding_id="s-1", title="Critical concern", category="security", severity="CRITICAL", confidence=0.5)]
    app = display(report(originals))
    assert app.success[0].value == "Review status: completed"
    assert [(item.label, item.value) for item in app.metric] == [("CRITICAL", "1"), ("HIGH", "1"), ("MEDIUM", "0"), ("LOW", "1")]
    assert [item.label for item in app.expander] == ["Finding 1 · CRITICAL", "Finding 2 · HIGH", "Finding 3 · LOW"]
    titles = [item.value for item in app.text if item.value.startswith("Title:")]
    assert titles == ["Title: Critical concern", "Title: Boundary concern", "Title: Low concern"]
    assert all(item.proto.language == "python" for item in app.code)
    assert [item.value for item in app.code[1:]] == ["    return value"] * 3
    assert app.session_state.review_report.findings[0].representative.evidence == "    return value"
    text = [item.value for item in app.text]
    for expected in ("Filename: example.py", "Source lines: 2", "Check boundary behavior.",
                     "Validate expected behavior.", "test_zero: input=0; expected=0",
                     "Model findings require engineering verification."):
        assert expected in text
    assert any("Confidence: 0.85" in value for value in text)


def test_duplicate_original_provenance_and_variants():
    app = display(report([finding(), finding(agent="security", finding_id="s-1", severity="MEDIUM",
        confidence=0.6, recommendation="An alternate remediation.", evidence="return value")]))
    assert len(app.expander) == 1
    text = [item.value for item in app.text]
    assert "Code Quality Reviewer · Finding ID: q-1" in text
    assert "Security Reviewer · Finding ID: s-1" in text
    assert "An alternate remediation." in text
    assert any("Confidence: 0.6" in value for value in text)


@pytest.mark.parametrize("status", ["completed", "partial", "failed"])
def test_zero_findings_are_distinguished_from_failure(status):
    app = display(report(status=status))
    assert len(app.expander) == 0
    assert all(item.value == "0" for item in app.metric)
    if status == "completed":
        assert "zero accepted findings" in app.info[0].value
        assert not app.warning
    else:
        assert "did not complete a successful clean review" in app.info[0].value
        assert any("agents failed" in item.value for item in app.warning)
    assert "PRIVATE_PROVIDER_BODY" not in str([item.value for item in app.text])


def test_partial_keeps_successful_findings_and_warning():
    app = display(report([finding()], status="partial"))
    assert len(app.expander) == 1
    assert app.warning[0].value == "Review status: partial"
    assert any("agents failed" in item.value for item in app.warning)
    assert "failed · review unavailable" in " ".join(item.value for item in app.markdown)


def test_model_html_and_markdown_are_only_plain_text():
    payload = '<script>alert(1)</script> [click](https://example.invalid) **text**'
    app = display(report([finding(title=payload, description=payload, recommendation=payload, suggested_tests=[payload])]))
    assert payload in [item.value for item in app.text]
    assert payload not in " ".join(item.value for item in app.markdown)
    assert not app.get("html")


def test_secret_in_model_report_is_blocked(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "FAKE_DASHBOARD_SECRET_VALUE")
    app = display(report([finding(recommendation="FAKE_DASHBOARD_SECRET_VALUE")]))
    assert "potentially sensitive content" in app.error[0].value
    assert not app.expander
    assert "FAKE_DASHBOARD_SECRET_VALUE" not in " ".join(item.value for item in [*app.text, *app.markdown, *app.error])


def test_rerun_persists_details_and_upload_change_invalidates():
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report([finding()])) as service:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        app.run()
        assert not app.exception and len(app.expander) == 1
        service.assert_called_once()
        with patch("streamlit.file_uploader", return_value=Upload("other.py")):
            app.run()
        assert not app.expander and app.session_state.review_report is None
        service.assert_called_once()


@pytest.mark.parametrize("changes,location", [({"line_number": 1, "end_line": 2}, "Source lines: 1–2"),
    ({"line_number": None}, "Source lines: Not specified")])
def test_source_range_and_optional_test_suggestions(changes, location):
    app = display(report([finding(**changes, suggested_tests=None)]))
    text = [item.value for item in app.text]
    assert location in text
    assert "No test scenarios were supplied for this finding." in text
