"""Safe typed error categories survive every layer; messages are never trusted."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import APIConnectionError, APITimeoutError
import pytest

from reviewguard.agents.code_quality import CodeQualityReviewer
from reviewguard.agents.security import SecurityReviewer
from reviewguard.agents.test_coverage import TestCoverageReviewer
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.models import ReviewReport
from reviewguard.reports.export import export_report_json
from reviewguard.schemas import AgentReviewResult, AgentType, ErrorCategory, ReviewFinding

SOURCE = "pass\n"


def success(agent):
    return AgentReviewResult(agent=agent, status="success", findings=[ReviewFinding(
        finding_id="kept", agent=agent, title="Synthetic concern", category="logic", severity="LOW",
        filename="example.py", line_number=1, evidence="pass", description="Test fixture.",
        recommendation="Check behavior.", confidence=0.5, suggested_tests=["test_case: input=1; expected=1"])])


@pytest.mark.parametrize("category", list(ErrorCategory))
def test_category_survives_graph_aggregation_report_and_export(category, caplog, capsys):
    failed = AgentReviewResult(agent="test_coverage", status="failed", findings=[],
        error_message="PRIVATE_API_KEY_UPLOADED_SOURCE_RAW_PROVIDER", error_category=category)
    graph = build_review_graph(code_quality=lambda f, s: success(AgentType.code_quality),
        security=lambda f, s: AgentReviewResult(agent="security", status="success", findings=[]),
        test_coverage=lambda f, s, **kw: failed)
    before = logging.root.manager.disable
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as network:
        output = asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    network.assert_not_called()
    assert output["workflow_status"] == "partial"
    actual = output["agent_results"][AgentType.test_coverage]
    assert actual.status == "failed" and actual.findings == [] and actual.error_category == category
    assert len(output["agent_results"][AgentType.code_quality].findings) == 1
    report = ReviewReport.model_validate(output["consolidated_report"])
    exported = export_report_json(report)
    status = next(item for item in report.agent_statuses if item.agent == AgentType.test_coverage)
    assert status.error_category == category
    assert json.loads(exported)["agent_statuses"][2]["error_category"] == category.value
    assert "PRIVATE" not in exported + actual.model_dump_json() + caplog.text + capsys.readouterr().out
    assert logging.root.manager.disable == before


@pytest.mark.parametrize("value", [None, "PRIVATE_SECRET_VALUE", 42, {"secret": "PRIVATE"}, "output truncated"])
def test_missing_and_unrecognized_category_become_unknown(value):
    result = AgentReviewResult(agent="security", status="failed", error_category=value)
    assert result.error_category == ErrorCategory.unknown_error
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize("reviewer,agent", [(CodeQualityReviewer, AgentType.code_quality),
    (SecurityReviewer, AgentType.security), (TestCoverageReviewer, AgentType.test_coverage)])
@pytest.mark.parametrize("failure,category", [
    ("invalid_json", "invalid_json"), ("invalid_schema", "invalid_schema"),
    ("invalid_source_evidence", "invalid_source_evidence"), ("length", "output_truncated"),
    ("missing_reason", "unknown_error"), ("timeout", "api_timeout"),
    ("provider", "provider_error"), ("unknown", "unknown_error"),
])
def test_real_agents_assign_known_categories(reviewer, agent, failure, category):
    client = Mock()
    client.with_options.return_value = client
    reason = "length" if failure == "length" else None if failure == "missing_reason" else "stop"
    payload = AgentReviewResult(agent=agent, status="success", findings=[]).model_dump_json()
    if failure == "invalid_json":
        payload = "PRIVATE_NOT_JSON"
    elif failure == "invalid_schema":
        payload = "{}"
    elif failure == "invalid_source_evidence":
        value = success(agent)
        value.findings[0].evidence = "PRIVATE_NOT_IN_SOURCE"
        payload = value.model_dump_json()
    request = httpx.Request("POST", "https://example.invalid")
    exceptions = {"timeout": APITimeoutError(request=request),
        "provider": APIConnectionError(message="PRIVATE_PROVIDER_BODY", request=request),
        "unknown": RuntimeError("PRIVATE_UNKNOWN")}
    if failure in exceptions:
        client.chat.completions.create.side_effect = exceptions[failure]
    else:
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=reason, message=SimpleNamespace(content=payload))])
    result = reviewer(client, "mock-model").review("example.py", SOURCE)
    assert result.status == "failed" and not result.findings
    assert result.error_category.value == category
    assert "PRIVATE" not in result.model_dump_json()
    client.chat.completions.create.assert_called_once()
    client.with_options.assert_called_once_with(timeout=30.0, max_retries=0)


def test_coverage_count_failure_is_explicit():
    client = Mock()
    client.with_options.return_value = client
    value = success(AgentType.test_coverage)
    value.findings[0].suggested_tests *= 6
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=value.model_dump_json()))])
    result = TestCoverageReviewer(client, "m").review("example.py", SOURCE)
    assert result.error_category == ErrorCategory.recommendation_limit_exceeded
    assert not result.findings


@pytest.mark.parametrize("kind,expected", [("timeout", "api_timeout"), ("provider", "provider_error"), ("unknown", "unknown_error")])
def test_raised_exceptions_are_classified_without_message_guessing(kind, expected):
    def fail(filename, source):
        if kind == "timeout":
            raise TimeoutError("PRIVATE")
        if kind == "provider":
            raise APIConnectionError(message="PRIVATE", request=httpx.Request("POST", "https://example.invalid"))
        raise ValueError("invalid_json PRIVATE")
    graph = build_review_graph(code_quality=fail,
        security=lambda f, s: AgentReviewResult(agent="security", status="success", findings=[]),
        test_coverage=lambda f, s, **kw: AgentReviewResult(agent="test_coverage", status="success", findings=[]))
    output = asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    assert output["agent_results"][AgentType.code_quality].error_category.value == expected
    assert "PRIVATE" not in str(output["consolidated_report"])
