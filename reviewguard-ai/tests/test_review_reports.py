"""Offline reports reuse grounded aggregation and preserve model assignments."""

from copy import deepcopy
from datetime import datetime, timezone
from itertools import permutations
import json
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.reports.builder import build_review_report
from reviewguard.reports.export import UnsafeReportError, export_report_json
from reviewguard.reports.models import ReviewReport
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding, Severity

SOURCE = "# FULL_SOURCE_PRIVATE_SENTINEL\nreturn value\n# never export this line\n"
STAMP = datetime(2026, 11, 3, tzinfo=timezone.utc)
IDENTITY = UUID("00000000-0000-0000-0000-000000000001")


def finding(**changes):
    return ReviewFinding.model_validate(dict({
        "finding_id": "q-1", "agent": "code_quality", "title": "Test concern", "category": "logic",
        "severity": "HIGH", "filename": "example.py", "line_number": 2,
        "description": "Synthetic supported concern.", "evidence": "return value",
        "recommendation": "Check returned value.", "confidence": 0.9,
        "suggested_tests": ["test_result: inputs=1; expected=1"],
    }, **changes))


def aggregation(findings=(), statuses=None):
    results = {agent: AgentReviewResult(agent=agent, status=(statuses or {}).get(agent, "success"),
        findings=[item for item in findings if item.agent == agent]) for agent in AgentType}
    return aggregate_findings(results, sources={"example.py": SOURCE})


def report(value=None):
    return build_review_report(value if value is not None else aggregation(), filename="example.py", report_id=IDENTITY, generated_at=STAMP)


@pytest.mark.parametrize("statuses,expected", [({}, "completed"), ({AgentType.security: "failed"}, "partial"),
    ({agent: "failed" for agent in AgentType}, "failed"), ({agent: "skipped" for agent in AgentType}, "failed")])
def test_review_statuses_and_empty_successes(statuses, expected):
    value = report(aggregation(statuses=statuses))
    assert value.workflow_status == expected and value.total_unique_findings == 0
    assert all(count == 0 for count in value.counts_by_severity.values())
    assert all(item.status == statuses.get(item.agent, "success") for item in value.agent_statuses)
    assert not any("zero issues" in (item.error_message or "") for item in value.agent_statuses)
    assert len(value.warnings) == 2


def test_priorities_counts_provenance_and_exact_fields():
    originals = [finding(), finding(agent="security", finding_id="s-1"),
        finding(title="Different issue", finding_id="q-2", severity="CRITICAL", confidence=0.4)]
    value = report(aggregation(originals))
    assert value.total_unique_findings == 2
    assert value.counts_by_severity == {Severity.CRITICAL: 1, Severity.HIGH: 1, Severity.MEDIUM: 0, Severity.LOW: 0}
    assert [item.representative.severity.value for item in value.findings] == ["CRITICAL", "HIGH"]
    group = value.findings[1]
    assert {item.agent for item in group.provenance} == {AgentType.code_quality, AgentType.security}
    assert {item.finding_id for item in group.provenance} == {"q-1", "s-1"}
    assert all(item.evidence == "return value" and item.confidence == 0.9 for item in group.original_findings)
    assert group.representative.recommendation == originals[0].recommendation
    assert group.representative.suggested_tests == originals[0].suggested_tests


def test_one_finding_roundtrip_and_no_source_or_metrics():
    value = report(aggregation([finding()]))
    encoded = export_report_json(value)
    assert ReviewReport.model_validate_json(encoded) == value
    assert "FULL_SOURCE_PRIVATE_SENTINEL" not in encoded
    assert "never export this line" not in encoded
    assert "source_code" not in json.loads(encoded)
    assert "coverage_percentage" not in encoded and "coverage_percent" not in encoded
    assert value.generated_at.utcoffset().total_seconds() == 0


def test_error_metadata_is_always_sanitized():
    value = aggregation(statuses={AgentType.security: "failed"})
    data = value.model_dump()
    for item in data["agent_statuses"]:
        item["error_message"] = "PRIVATE_RAW_PROVIDER_API_KEY"
    rebuilt = report(type(value).model_validate(data))
    assert "PRIVATE_RAW_PROVIDER_API_KEY" not in export_report_json(rebuilt)
    assert all(item.error_message is None for item in rebuilt.agent_statuses if item.status == "success")


def test_order_stability_and_input_isolation():
    originals = [finding(agent=agent, finding_id=agent.value) for agent in AgentType]
    expected = report(aggregation(originals)).model_dump_json()
    for order in permutations(originals):
        assert report(aggregation(order)).model_dump_json() == expected
    value = aggregation(originals)
    before = deepcopy(value)
    built = report(value)
    built.findings[0].representative.recommendation = "Changed by owner"
    assert value == before


def test_generated_id_and_timestamp_are_only_variable_fields():
    first = build_review_report(aggregation([finding()]), filename="example.py")
    second = build_review_report(aggregation([finding()]), filename="example.py")
    assert first.report_id != second.report_id
    assert first.model_dump(exclude={"report_id", "generated_at"}) == second.model_dump(exclude={"report_id", "generated_at"})


@pytest.mark.parametrize("secret", ["fw_" + "x" * 32, "-----BEGIN PRIVATE KEY-----", 'password = "example-sensitive-value"'])
def test_common_secret_patterns_block_export(secret):
    value = report(aggregation([finding(recommendation=secret)]))
    with pytest.raises(UnsafeReportError) as error:
        export_report_json(value)
    assert secret not in str(error.value)


def test_environment_and_explicit_secrets_block_export(monkeypatch):
    secret = "fake-configured-value-with-quotes'and-newline\n"
    monkeypatch.setenv("FIREWORKS_API_KEY", secret)
    value = report(aggregation([finding(description=secret)]))
    with pytest.raises(UnsafeReportError):
        export_report_json(value)
    with pytest.raises(UnsafeReportError):
        export_report_json(report(aggregation([finding(title="custom-sensitive-value")])), sensitive_values=["custom-sensitive-value"])


def test_dotenv_secret_blocked_without_exposure():
    value = report(aggregation([finding(title="fake-dotenv-secret-value")]))
    with patch("reviewguard.reports.export.dotenv_values", return_value={"FIREWORKS_API_KEY": "fake-dotenv-secret-value"}):
        with pytest.raises(UnsafeReportError):
            export_report_json(value)


def test_report_generation_has_no_network_or_execution(tmp_path):
    # Source has already been grounded upstream; the builder accepts no source.
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as network:
        value = report(aggregation([finding()]))
        export_report_json(value)
    network.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_dotenv_secret_is_checked_even_when_environment_overrides_it(monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "different-runtime-secret")
    value = report(aggregation([finding(title="fake-dotenv-secret-value")]))
    with patch("reviewguard.reports.export.dotenv_values", return_value={"FIREWORKS_API_KEY": "fake-dotenv-secret-value"}):
        with pytest.raises(UnsafeReportError):
            export_report_json(value)


@pytest.mark.parametrize("changes", [{"total_unique_findings": 99}, {"counts_by_severity": {}},
    {"warnings": []}, {"source_code": SOURCE}, {"generated_at": datetime(2026, 11, 3)}])
def test_invalid_summary_and_full_source_field_rejected(changes):
    data = report().model_dump()
    with pytest.raises(ValidationError):
        ReviewReport.model_validate({**data, **changes})
