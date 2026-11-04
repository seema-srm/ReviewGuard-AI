"""Offline end-to-end verification through graph, aggregation and report export.

Findings are prescribed test fixtures, not claims about model detection quality.
"""

import asyncio
import builtins
from copy import deepcopy
from itertools import permutations
from threading import Barrier, Event, Lock
from types import CodeType
from unittest.mock import patch
from uuid import UUID

import pytest

from reviewguard.orchestration.graph import aggregate_results, build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.export import UnsafeReportError, export_report_json
from reviewguard.reports.models import ReviewReport
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding, Severity, validate_finding_against_source

SOURCE = (
    "# FULL_UPLOADED_SOURCE_SENTINEL\n"
    "def divide(total, count):\n"
    "    return total / count\n"
    "\n"
    "raise RuntimeError('E2E_SOURCE_NEVER_EXECUTED')\n"
)


@pytest.fixture(autouse=True)
def offline_guards():
    original_exec = builtins.exec
    attempts = []

    def guarded_exec(code, *args, **kwargs):
        if (isinstance(code, str) and "E2E_SOURCE_NEVER_EXECUTED" in code) or (
            isinstance(code, CodeType) and "E2E_SOURCE_NEVER_EXECUTED" in code.co_consts
        ):
            attempts.append("source execution")
            raise AssertionError("Uploaded source execution prohibited")
        return original_exec(code, *args, **kwargs)

    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as sync_send, \
         patch("httpx.AsyncClient.send", side_effect=AssertionError("Network prohibited")) as async_send, \
         patch("reviewguard.fireworks_client.OpenAI", side_effect=AssertionError("SDK prohibited")) as sdk, \
         patch("reviewguard.reports.export.dotenv_values", return_value={"FIREWORKS_API_KEY": "E2E_FAKE_CONFIGURED_SECRET"}), \
         patch("builtins.exec", side_effect=guarded_exec):
        yield
    sync_send.assert_not_called()
    async_send.assert_not_called()
    sdk.assert_not_called()
    assert attempts == []


def finding(agent, finding_id, *, title="Division by zero", category="logic", severity="HIGH", confidence=0.8,
            recommendation="Validate count before division.", filename="example.py"):
    return ReviewFinding(
        finding_id=finding_id, agent=agent, title=title, category=category, severity=severity,
        filename=filename, line_number=3, end_line=3,
        description="The operation uses count as its divisor.", evidence="    return total / count",
        recommendation=recommendation, confidence=confidence,
        suggested_tests=["test_zero_count: inputs=(1,0); expected=ZeroDivisionError"],
    )


def responses(filename="example.py"):
    return {
        AgentType.code_quality: AgentReviewResult(agent="code_quality", status="success", findings=[
            finding(AgentType.code_quality, "q-1", filename=filename),
            finding(AgentType.code_quality, "q-2", title="Numeric type behavior", category="types", severity="LOW", filename=filename),
        ]),
        AgentType.security: AgentReviewResult(agent="security", status="success", findings=[
            finding(AgentType.security, "s-1", severity="MEDIUM", confidence=0.7,
                recommendation="Reject a zero divisor at the boundary.", filename=filename),
            finding(AgentType.security, "s-2", title="Synthetic security concern", category="security",
                severity="CRITICAL", confidence=0.6, filename=filename),
        ]),
        AgentType.test_coverage: AgentReviewResult(agent="test_coverage", status="success", findings=[
            finding(AgentType.test_coverage, "t-1", title="Recommended divisor boundary test",
                category="recommended_test", severity="MEDIUM", filename=filename),
        ]),
    }


def validate_export(output):
    report = ReviewReport.model_validate(output["consolidated_report"])
    encoded = export_report_json(report)
    assert ReviewReport.model_validate_json(encoded) == report
    assert isinstance(report.report_id, UUID)
    assert report.generated_at.tzinfo is not None and report.generated_at.utcoffset().total_seconds() == 0
    assert report.workflow_status == output["workflow_status"]
    for group in report.findings:
        validate_finding_against_source(group.representative, SOURCE, filename=report.filename)
        for item in group.original_findings:
            validate_finding_against_source(item, SOURCE, filename=report.filename)
    for prohibited in ("FULL_UPLOADED_SOURCE_SENTINEL", "E2E_SOURCE_NEVER_EXECUTED", "source_code",
                       "E2E_FAKE_CONFIGURED_SECRET", "RAW_PROVIDER_BODY", "coverage_percentage"):
        assert prohibited not in encoded
    return report


@pytest.mark.parametrize("order", list(permutations(tuple(AgentType))))
def test_complete_end_to_end_in_every_completion_order(order):
    prescribed = responses()
    before = deepcopy(prescribed)
    barrier = Barrier(3, timeout=5)
    finished = {agent: Event() for agent in AgentType}
    calls, completion_order, aggregations = [], [], []
    lock = Lock()

    def review(agent, filename, source, **kwargs):
        assert filename == "example.py" and source == SOURCE
        if agent == AgentType.test_coverage:
            assert kwargs == {"existing_tests": None, "measured_coverage": None}
        with lock:
            calls.append(agent)
        barrier.wait()
        assert len(calls) == 3
        index = order.index(agent)
        if index:
            assert finished[order[index - 1]].wait(5)
        completion_order.append(agent)
        finished[agent].set()
        return prescribed[agent]

    def aggregate(state):
        assert all(event.is_set() for event in finished.values())
        aggregations.append(deepcopy(state))
        return aggregate_results(state)

    initial = create_initial_state("example.py", SOURCE)
    original_state = deepcopy(initial)
    with patch("reviewguard.orchestration.graph.aggregate_results", side_effect=aggregate):
        graph = build_review_graph(code_quality=lambda f, s: review(AgentType.code_quality, f, s),
            security=lambda f, s: review(AgentType.security, f, s),
            test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw))
        output = asyncio.run(graph.ainvoke(initial))
    report = validate_export(output)
    assert completion_order == list(order) and len(aggregations) == 1
    assert set(calls) == set(AgentType) and len(calls) == 3
    assert report.workflow_status == "completed" and report.total_unique_findings == 4
    assert report.counts_by_severity == {Severity.CRITICAL: 1, Severity.HIGH: 1, Severity.MEDIUM: 1, Severity.LOW: 1}
    assert [group.representative.severity.value for group in report.findings] == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    duplicate = report.findings[1]
    assert {(item.agent, item.finding_id) for item in duplicate.provenance} == {
        (AgentType.code_quality, "q-1"), (AgentType.security, "s-1")}
    assert len(duplicate.original_findings) == 2
    assert {item.recommendation for item in duplicate.original_findings} == {
        before[AgentType.code_quality].findings[0].recommendation, before[AgentType.security].findings[0].recommendation}
    actual_originals = [item.model_dump_json() for group in report.findings for item in group.original_findings]
    supplied_originals = [item.model_dump_json() for result in prescribed.values() for item in result.findings]
    assert sorted(actual_originals) == sorted(supplied_originals)  # No loss or fabrication.
    assert initial == original_state and prescribed == before
    assert output["agent_results"] == before


@pytest.mark.parametrize("mode,expected", [("partial", "partial"), ("all_failed", "failed"), ("clean", "completed")])
def test_empty_success_partial_and_all_failed_reports(mode, expected):
    calls = []

    def review(agent, filename, source, **kwargs):
        calls.append(agent)
        if mode == "all_failed" or (mode == "partial" and agent == AgentType.security):
            raise RuntimeError("RAW_PROVIDER_BODY E2E_FAKE_CONFIGURED_SECRET")
        if mode == "partial" and agent == AgentType.code_quality:
            return responses()[agent]
        return AgentReviewResult(agent=agent, status="success", findings=[])

    with patch("reviewguard.orchestration.graph.aggregate_results", wraps=aggregate_results) as aggregate:
        graph = build_review_graph(code_quality=lambda f, s: review(AgentType.code_quality, f, s),
            security=lambda f, s: review(AgentType.security, f, s),
            test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw))
        output = asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    aggregate.assert_called_once()
    assert len(calls) == 3
    report = validate_export(output)
    assert report.workflow_status == expected
    assert report.total_unique_findings == (2 if mode == "partial" else 0)
    statuses = {item.agent: item for item in report.agent_statuses}
    if mode == "partial":
        assert statuses[AgentType.security].status == "failed" and statuses[AgentType.security].error_message
        clean = output["agent_results"][AgentType.test_coverage]
        assert clean.status == "success" and clean.findings == [] and clean.error_message is None
    if mode == "all_failed":
        assert all(item.status == "failed" and item.error_message for item in statuses.values())


def test_repeated_and_concurrent_invocations_are_isolated_and_deterministic():
    def review(agent, filename, source, **kwargs):
        return responses(filename)[agent]

    graph = build_review_graph(code_quality=lambda f, s: review(AgentType.code_quality, f, s),
        security=lambda f, s: review(AgentType.security, f, s),
        test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw))

    async def run():
        first = await graph.ainvoke(create_initial_state("example.py", SOURCE))
        others = await asyncio.gather(graph.ainvoke(create_initial_state("example.py", SOURCE)),
                                     graph.ainvoke(create_initial_state("second.py", SOURCE)))
        return first, *others

    first, second, other = asyncio.run(run())
    one, two, alternate = [validate_export(item) for item in (first, second, other)]
    assert one.report_id != two.report_id
    assert one.model_dump(exclude={"report_id", "generated_at"}) == two.model_dump(exclude={"report_id", "generated_at"})
    assert alternate.filename == "second.py"
    assert all(item.filename == "second.py" for group in alternate.findings for item in group.original_findings)
    first["agent_results"][AgentType.code_quality].findings.clear()
    assert len(second["agent_results"][AgentType.code_quality].findings) == 2
    assert one.total_unique_findings == 4


def test_sensitive_finding_cannot_be_released_in_report():
    prescribed = responses()
    prescribed[AgentType.code_quality].findings[0].recommendation = "E2E_FAKE_CONFIGURED_SECRET"
    graph = build_review_graph(code_quality=lambda f, s: prescribed[AgentType.code_quality],
        security=lambda f, s: prescribed[AgentType.security],
        test_coverage=lambda f, s, **kw: prescribed[AgentType.test_coverage])
    with pytest.raises(UnsafeReportError) as error:
        asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    assert "E2E_FAKE_CONFIGURED_SECRET" not in str(error.value)


@pytest.mark.parametrize("invalid", ["evidence", "line"])
def test_unsupported_finding_fails_its_branch_without_fabrication(invalid):
    prescribed = responses()
    if invalid == "evidence":
        prescribed[AgentType.security].findings[0].evidence = "NOT_IN_SOURCE"
    else:
        prescribed[AgentType.security].findings[0].line_number = 99
        prescribed[AgentType.security].findings[0].end_line = 99
    graph = build_review_graph(code_quality=lambda f, s: prescribed[AgentType.code_quality],
        security=lambda f, s: prescribed[AgentType.security],
        test_coverage=lambda f, s, **kw: prescribed[AgentType.test_coverage])
    output = asyncio.run(graph.ainvoke(create_initial_state("example.py", SOURCE)))
    report = validate_export(output)
    assert report.workflow_status == "partial" and report.total_unique_findings == 3
    assert output["agent_results"][AgentType.security].status == "failed"
    assert not any(item.agent == AgentType.security for group in report.findings for item in group.original_findings)
