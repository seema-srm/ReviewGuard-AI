"""Deterministic aggregation, exact grounding and provenance regression tests."""

import asyncio
from copy import deepcopy
from itertools import permutations

import pytest

from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding, SourceValidationError

SOURCE = "return value\nreturn value\n"


def finding(**changes):
    return ReviewFinding.model_validate(dict({
        "finding_id": "q-1", "agent": "code_quality", "title": "Incorrect result",
        "category": "logic", "severity": "MEDIUM", "filename": "example.py",
        "line_number": 1, "description": "Result does not match the documented condition.",
        "evidence": "return value", "recommendation": "Correct the comparison.",
        "confidence": 0.8, "suggested_tests": ["test_boundary: input=1; expected=1"],
    }, **changes))


def results(*findings, statuses=None):
    return {agent: AgentReviewResult(agent=agent, status=(statuses or {}).get(agent, "success"),
        findings=[item for item in findings if item.agent == agent]) for agent in AgentType}


def aggregate(*findings, statuses=None, sources=None):
    return aggregate_findings(results(*findings, statuses=statuses), sources=sources or {"example.py": SOURCE})


def test_empty_successful_results() -> None:
    value = aggregate()
    assert value.workflow_status == "completed" and value.findings == ()
    assert len(value.agent_statuses) == 3


def test_one_finding_is_original_not_fabricated() -> None:
    original = finding()
    value = aggregate(original)
    assert len(value.findings) == 1
    assert value.findings[0].representative == original
    assert value.findings[0].original_findings == (original,)
    assert value.findings[0].representative is not original


def test_severity_then_confidence_ordering() -> None:
    originals = [finding(finding_id=str(index), title=f"Issue {index}", severity=severity, confidence=confidence)
        for index, (severity, confidence) in enumerate([("LOW", 1), ("HIGH", 0.5), ("CRITICAL", 0.1), ("MEDIUM", 0.9), ("HIGH", 0.9)])]
    value = aggregate(*originals)
    assert [item.representative.finding_id for item in value.findings] == ["2", "4", "1", "3", "0"]
    assert all(item.representative in originals for item in value.findings)


def test_exact_duplicates_retain_every_original() -> None:
    original = finding()
    group = aggregate(original, original.model_copy(deep=True)).findings[0]
    assert len(group.original_findings) == len(group.provenance) == 2
    assert all(item == original for item in group.original_findings)


def test_cross_agent_duplicates_preserve_provenance() -> None:
    originals = [finding(agent=agent, finding_id=f"{agent.value}-1") for agent in AgentType]
    value = aggregate(*originals)
    assert len(value.findings) == 1
    assert {item.agent for item in value.findings[0].provenance} == set(AgentType)
    assert {item.finding_id for item in value.findings[0].provenance} == {item.finding_id for item in originals}


@pytest.mark.parametrize("changes", [
    {"title": "A different concern"}, {"category": "security"},
    {"description": "A different underlying cause."}, {"line_number": 2},
    {"end_line": 2}, {"filename": "other.py"}, {"filename": "Example.py"},
])
def test_distinct_issues_never_merge(changes) -> None:
    value = aggregate(finding(), finding(finding_id="q-2", **changes),
        sources={"example.py": SOURCE, "other.py": SOURCE, "Example.py": SOURCE})
    assert len(value.findings) == 2


def test_distinct_agent_concerns_on_same_line() -> None:
    originals = [finding(agent=agent, title=f"{agent.value} concern", category=agent.value) for agent in AgentType]
    assert len(aggregate(*originals).findings) == 3


def test_evidence_recommendations_and_scores_are_not_lost() -> None:
    first = finding(severity="LOW", confidence=0.99)
    second = finding(agent="security", finding_id="s-1", evidence="value",
        recommendation="Use a different mitigation.", severity="HIGH", confidence=0.5)
    group = aggregate(first, second).findings[0]
    assert group.representative == second
    assert set(item.evidence for item in group.original_findings) == {"return value", "value"}
    assert {item.recommendation for item in group.original_findings} == {first.recommendation, second.recommendation}
    assert {(item.severity.value, item.confidence) for item in group.original_findings} == {("LOW", 0.99), ("HIGH", 0.5)}
    # Multiplicity cannot upgrade severity or confidence.
    repeated = aggregate(first, first.model_copy(update={"finding_id": "q-2"})).findings[0]
    assert repeated.representative.severity == first.severity
    assert repeated.representative.confidence == first.confidence


def test_filename_and_identity_normalization() -> None:
    other = finding(filename="./src\\example.py", title=" INCORRECT   RESULT ", category="LOGIC",
        description="result DOES NOT match the documented condition.", finding_id="q-2")
    first = finding(filename="src/example.py")
    assert len(aggregate(first, other, sources={first.filename: SOURCE, other.filename: SOURCE}).findings) == 1


def test_unknown_location_requires_exact_evidence() -> None:
    assert len(aggregate(finding(line_number=None), finding(line_number=None, evidence="value")).findings) == 2


@pytest.mark.parametrize("statuses,expected", [
    ({AgentType.security: "failed"}, "partial"),
    ({AgentType.security: "skipped"}, "partial"),
    ({agent: "failed" for agent in AgentType}, "failed"),
    ({agent: "skipped" for agent in AgentType}, "failed"),
])
def test_failure_statuses_preserved_separately(statuses, expected) -> None:
    originals = [finding(agent=agent) for agent in AgentType if statuses.get(agent, "success") == "success"]
    value = aggregate(*originals, statuses=statuses)
    assert value.workflow_status == expected
    for status in value.agent_statuses:
        assert status.status == statuses.get(status.agent, "success")
    successful = {agent for agent in AgentType if statuses.get(agent, "success") == "success"}
    assert {item.agent for group in value.findings for item in group.original_findings} == successful


def test_permutation_order_is_deterministic_and_inputs_unchanged() -> None:
    originals = [finding(agent=agent, finding_id=agent.value, confidence=0.8) for agent in AgentType]
    baseline = results(*originals)
    before = deepcopy(baseline)
    expected = aggregate_findings(baseline, sources={"example.py": SOURCE}).model_dump_json()
    for order in permutations(tuple(AgentType)):
        reordered = {agent: baseline[agent] for agent in order}
        assert aggregate_findings(reordered, sources={"example.py": SOURCE}).model_dump_json() == expected
    for order in permutations(originals):
        assert aggregate(*order).model_dump_json() == expected
    assert baseline == before


@pytest.mark.parametrize("changes", [{"evidence": "not present"}, {"line_number": 99}])
def test_source_validation_stays_strict(changes) -> None:
    with pytest.raises(SourceValidationError):
        aggregate(finding(**changes))


def test_missing_status_or_source_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate_findings({}, sources={})
    with pytest.raises(ValueError, match="Source unavailable"):
        aggregate_findings(results(finding()), sources={})


def test_graph_aggregation_integration_preserves_partial_results() -> None:
    graph = build_review_graph(code_quality=lambda f, s: results(finding())[AgentType.code_quality],
        security=lambda f, s: AgentReviewResult(agent="security", status="failed", error_message="PRIVATE"),
        test_coverage=lambda f, s, **kw: results()[AgentType.test_coverage])
    value = asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    report = value["consolidated_report"]
    assert value["workflow_status"] == report["workflow_status"] == "partial"
    assert len(report["findings"]) == 1
    assert report["findings"][0]["representative"] == finding().model_dump(mode="json")
    assert "PRIVATE" not in str(report)


def test_stable_ties_and_member_order_within_same_agent() -> None:
    originals = [finding(finding_id="b", title="Beta"), finding(finding_id="a", title="Alpha"),
                 finding(finding_id="c", title="Alpha", confidence=0.9)]
    expected = aggregate(*originals).model_dump_json()
    for order in permutations(originals):
        assert aggregate(*order).model_dump_json() == expected
    groups = aggregate(*originals).findings
    assert [item.representative.finding_id for item in groups] == ["c", "b"]
    assert [item.finding_id for item in groups[0].original_findings] == ["c", "a"]
