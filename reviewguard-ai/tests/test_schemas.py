"""Offline contract tests using synthetic findings, not generated reviews."""

import json

import pytest
from pydantic import ValidationError

from reviewguard.schemas import (
    AgentReviewResult, AgentType, ReviewFinding, Severity,
    SourceValidationError, validate_finding_against_source,
)


@pytest.fixture
def finding_data() -> dict:
    return {
        "finding_id": "quality-1", "agent": "code_quality",
        "title": "Check return value", "category": "logic", "severity": "LOW",
        "filename": "example.py", "line_number": 2,
        "description": "Test description", "evidence": "    return value",
        "recommendation": "Check the expected result", "confidence": 0.8,
    }


def test_valid_finding_and_optional_fields(finding_data: dict) -> None:
    finding = ReviewFinding.model_validate(finding_data)
    assert finding.agent is AgentType.code_quality
    assert finding.severity is Severity.LOW
    assert finding.end_line is None
    assert finding.suggested_tests is None
    assert ReviewFinding.model_validate({**finding_data, "suggested_tests": ["Check zero input"]}).suggested_tests == ["Check zero input"]


@pytest.mark.parametrize("field, value", [
    ("severity", "urgent"), ("agent", "unknown"),
    ("confidence", -0.1), ("confidence", 1.1),
    ("confidence", float("nan")), ("confidence", float("inf")),
    ("line_number", 0), ("line_number", -1), ("line_number", True),
    ("line_number", 1.5), ("end_line", 0), ("end_line", -1),
    ("end_line", 1), ("title", " "), ("evidence", ""),
])
def test_invalid_finding(finding_data: dict, field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate({**finding_data, field: value})


@pytest.mark.parametrize("confidence", [0, 1])
def test_confidence_boundaries(finding_data: dict, confidence: float) -> None:
    assert ReviewFinding.model_validate({**finding_data, "confidence": confidence}).confidence == confidence


def test_end_line_requires_start(finding_data: dict) -> None:
    with pytest.raises(ValidationError, match="requires line_number"):
        ReviewFinding.model_validate({**finding_data, "line_number": None, "end_line": 2})


@pytest.mark.parametrize("agent", list(AgentType))
@pytest.mark.parametrize("status", ["success", "failed", "skipped"])
def test_empty_results(agent: AgentType, status: str) -> None:
    result = AgentReviewResult(agent=agent, status=status, findings=[])
    assert result.findings == []


def test_multiple_findings_and_json_roundtrip(finding_data: dict) -> None:
    result = AgentReviewResult.model_validate({
        "agent": "code_quality", "status": "success", "findings": [
            finding_data, {**finding_data, "finding_id": "quality-2", "severity": "HIGH"},
        ],
    })
    encoded = result.model_dump_json()
    assert json.loads(encoded)["findings"][1]["severity"] == "HIGH"
    assert AgentReviewResult.model_validate_json(encoded) == result
    finding = result.findings[0]
    assert ReviewFinding.model_validate_json(finding.model_dump_json()) == finding


@pytest.mark.parametrize("changes", [
    {"agent": "security"}, {"agent": "unknown"}, {"status": "pending"},
    {"status": "failed"}, {"status": "skipped"}, {"error_message": "failure"},
])
def test_invalid_results(finding_data: dict, changes: dict) -> None:
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate({"agent": "code_quality", "status": "success", "findings": [finding_data], **changes})


def test_errors_remain_separate_and_parse_failures_raise() -> None:
    failed = AgentReviewResult(agent="security", status="failed", error_message="Invalid model response")
    assert failed.findings == []
    assert AgentReviewResult.model_validate_json(failed.model_dump_json()) == failed
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate_json('{"agent":"security","status":"success","findings":[{}]}')
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate_json("not JSON")
    assert failed.findings == []


@pytest.mark.parametrize("changes, source", [
    ({}, "def example(value):\n    return value\n"),
    ({"end_line": 2}, "def example(value):\n    return value\n"),
    ({"line_number": None}, "def example(value):\n    return value\n"),
    ({"line_number": 1, "end_line": 2, "evidence": "def example(value):\n    return value"}, "def example(value):\n    return value\n"),
    ({"line_number": 1, "end_line": 2, "evidence": "# header\r\n    return value"}, "# header\r\n    return value\r\n"),
])
def test_exact_source_validation(finding_data: dict, changes: dict, source: str) -> None:
    finding = ReviewFinding.model_validate({**finding_data, **changes})
    assert validate_finding_against_source(finding, source, filename="example.py") is finding


@pytest.mark.parametrize("changes, source, filename", [
    ({}, "header\n    return value", "other.py"),
    ({"line_number": 3}, "header\n    return value\n", "example.py"),
    ({"end_line": 3}, "header\n    return value\n", "example.py"),
    ({}, "", "example.py"),
    ({"line_number": 1}, "header\n    return value", "example.py"),
    ({"evidence": "return other"}, "header\n    return value", "example.py"),
    ({"evidence": "  return  value"}, "header\n    return value", "example.py"),
    ({"line_number": None}, "", "example.py"),
    ({"line_number": 1, "end_line": 2, "evidence": "header\n    return value"}, "header\r\n    return value", "example.py"),
])
def test_unsupported_source_references(finding_data: dict, changes: dict, source: str, filename: str) -> None:
    finding = ReviewFinding.model_validate({**finding_data, **changes})
    with pytest.raises(SourceValidationError):
        validate_finding_against_source(finding, source, filename=filename)


def test_unknown_fields_are_rejected(finding_data: dict) -> None:
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate({**finding_data, "invented_field": "ignored?"})
