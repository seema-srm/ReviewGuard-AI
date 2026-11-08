"""Mock-only UI submissions and event-loop-safe workflow entry tests."""

import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from reviewguard.file_utils import validate_python_file
from reviewguard.fireworks_client import ConfigurationError
from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.builder import build_review_report
from reviewguard.schemas import AgentReviewResult, AgentType, ErrorCategory
from reviewguard.ui.review_service import run_review

APP = Path(__file__).resolve().parents[1] / "app.py"


class Upload(BytesIO):
    def __init__(self, name="example.py", content=b"pass\n"):
        super().__init__(content)
        self.name, self.size = name, len(content)


def report(status="completed", filename="example.py"):
    results = {agent: AgentReviewResult(agent=agent, status="failed" if status == "failed" or
        (status == "partial" and agent == AgentType.security) else "success", findings=[])
        for agent in AgentType}
    return build_review_report(aggregate_findings(results, sources={filename: "pass\n"}), filename=filename)


@pytest.fixture(autouse=True)
def block_network():
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as send:
        yield
    send.assert_not_called()


def test_click_only_once_and_report_persists_on_rerun():
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report()) as service:
        app = AppTest.from_file(str(APP)).run()
        service.assert_not_called()
        app.button(key="submit_review").click().run()
        assert not app.exception and app.success[0].value == "Review status: completed"
        assert app.session_state.review_report is not None
        service.assert_called_once()
        app.run()
        assert not app.exception and app.session_state.review_report is not None
        assert app.button(key="submit_review").disabled
        service.assert_called_once()
        # Re-arming never sends a paid request; a separate review click is required.
        next(button for button in app.button if button.label == "Enable another review").click().run()
        service.assert_called_once()
        assert not app.button(key="submit_review").disabled
        app.button(key="submit_review").click().run()
        assert service.call_count == 2


@pytest.mark.parametrize("upload", [Upload("other.py"), Upload(content=b"x = 1\n"), None, Upload("bad.txt")])
def test_changed_or_invalid_upload_clears_report_without_review(upload):
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report()) as service:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        assert app.session_state.review_report is not None
        with patch("streamlit.file_uploader", return_value=upload):
            app.run()
        assert not app.exception and app.session_state.review_report is None
        assert "No review has been run" in app.info[0].value
        service.assert_called_once()


@pytest.mark.parametrize("status", ["completed", "partial", "failed"])
def test_ui_execution_statuses_with_no_fabricated_findings(status):
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", return_value=report(status)):
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
    assert not app.exception
    alerts = [item.value for item in [*app.success, *app.warning, *app.error]]
    assert f"Review status: {status}" in alerts
    assert app.session_state.review_report.total_unique_findings == 0
    text = " ".join(item.value for item in app.markdown)
    if status in ("completed", "partial"):
        assert "success · 0 findings" in text
    if status in ("partial", "failed"):
        assert "failed · review unavailable" in text


def test_graph_failure_category_is_visible_in_streamlit_without_sensitive_details():
    graph = build_review_graph(
        code_quality=lambda f, s: AgentReviewResult(agent=AgentType.code_quality, status="success"),
        security=lambda f, s: AgentReviewResult(agent=AgentType.security, status="success"),
        test_coverage=lambda f, s, **kw: AgentReviewResult(
            agent=AgentType.test_coverage,
            status="failed",
            error_message="PRIVATE_SOURCE_PROVIDER_BODY",
            error_category=ErrorCategory.output_truncated,
        ),
    )
    output = asyncio.run(graph.ainvoke(create_initial_state("example.py", "pass\n")))
    value = build_review_report(
        aggregate_findings(output["agent_results"], sources={"example.py": "pass\n"}),
        filename="example.py",
    )
    with patch("streamlit.file_uploader", return_value=Upload()), \
         patch("reviewguard.ui.review_service.run_review", return_value=value):
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
    assert not app.exception
    assert "Diagnostic category: output_truncated" in [item.value for item in app.caption]
    assert "PRIVATE" not in " ".join(item.value for item in [*app.caption, *app.markdown, *app.error])
    assert output["agent_results"][AgentType.test_coverage].error_category == ErrorCategory.output_truncated


@pytest.mark.parametrize("error,expected", [(ConfigurationError("PRIVATE_KEY"), "configuration"),
    (RuntimeError("PRIVATE_RAW_PROVIDER_SOURCE"), "Sensitive provider details are hidden")])
def test_ui_errors_are_safe_and_no_retry(error, expected, caplog):
    with patch("streamlit.file_uploader", return_value=Upload()), patch("reviewguard.ui.review_service.run_review", side_effect=error) as service:
        app = AppTest.from_file(str(APP)).run()
        app.button(key="submit_review").click().run()
        assert not app.exception
        assert expected in app.error[0].value
        assert app.session_state.review_report is None and not app.session_state.review_running
        app.run()
        service.assert_called_once()
        assert "PRIVATE" not in " ".join(item.value for item in app.error) + caplog.text


def test_running_guard_disables_submission(mock_ui_review):
    with patch("streamlit.file_uploader", return_value=Upload()):
        app = AppTest.from_file(str(APP)).run()
        app.session_state.review_running = True
        app.run()
        assert app.button(key="submit_review").disabled
    mock_ui_review.assert_not_called()


@pytest.mark.parametrize("active_loop", [False, True])
def test_service_reuses_graph_once_with_loop_isolation(active_loop):
    value = report()
    graph = Mock()
    graph.ainvoke = AsyncMock(return_value={"workflow_status": "completed", "consolidated_report": value.model_dump(mode="json")})
    upload = validate_python_file("example.py", b"pass\n")
    with patch("reviewguard.ui.review_service.load_fireworks_settings") as settings, patch("reviewguard.ui.review_service.build_review_graph", return_value=graph) as factory:
        if active_loop:
            async def caller():
                return run_review(upload)
            actual = asyncio.run(caller())
        else:
            actual = run_review(upload)
    assert actual == value
    settings.assert_called_once()
    factory.assert_called_once()
    graph.ainvoke.assert_awaited_once()
    assert graph.ainvoke.call_args.args[0]["source_code"] == "pass\n"


def test_service_missing_configuration_prevents_graph_creation():
    with patch("reviewguard.ui.review_service.load_fireworks_settings", side_effect=ConfigurationError("safe")), patch("reviewguard.ui.review_service.build_review_graph") as factory:
        with pytest.raises(ConfigurationError):
            run_review(validate_python_file("example.py", b"pass"))
    factory.assert_not_called()
