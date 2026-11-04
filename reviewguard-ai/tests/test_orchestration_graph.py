"""Graph execution uses only injected offline reviewers."""

import asyncio
from copy import deepcopy
from itertools import permutations
from threading import Barrier, Lock
from unittest.mock import patch

import pytest

from reviewguard.orchestration.graph import aggregate_results, build_review_graph
from reviewguard.orchestration.state import create_initial_state, merge_agent_results
from reviewguard.schemas import AgentReviewResult, AgentType


def result(agent: AgentType, status: str = "success") -> AgentReviewResult:
    return AgentReviewResult(agent=agent, status=status, findings=[])


def test_construction_compiles_without_configuration_or_api_calls() -> None:
    with patch("reviewguard.fireworks_client.load_fireworks_settings", side_effect=AssertionError("No configuration")), patch("reviewguard.fireworks_client.OpenAI", side_effect=AssertionError("No API")), patch("reviewguard.orchestration.graph.CodeQualityReviewer") as quality, patch("reviewguard.orchestration.graph.SecurityReviewer") as security, patch("reviewguard.orchestration.graph.TestCoverageReviewer") as coverage:
        graph = build_review_graph()
    assert hasattr(graph, "ainvoke")
    quality.assert_not_called()
    security.assert_not_called()
    coverage.assert_not_called()


def test_parallel_branches_merge_and_aggregate_once_after_all_finish() -> None:
    barrier = Barrier(3, timeout=5)
    lock = Lock()
    finished = []
    initial = create_initial_state("example.py", "pass\n", existing_tests={"test_x.py": "pass"},
                                   measured_coverage={"filename": "example.py", "missing_lines": [1]})
    original = deepcopy(initial)

    def review(agent, filename, source, **kwargs):
        assert filename == "example.py" and source == "pass\n"
        if agent == AgentType.test_coverage:
            assert kwargs["existing_tests"] == initial["existing_tests"]
            assert kwargs["measured_coverage"] == initial["measured_coverage"]
            kwargs["existing_tests"].clear()
            kwargs["measured_coverage"]["missing_lines"].clear()
        barrier.wait()  # Requires three overlapping worker threads; no timing assertion.
        with lock:
            finished.append(agent)
        return result(agent)

    snapshots = []

    def aggregate(state):
        assert set(finished) == set(AgentType)
        snapshots.append(deepcopy(state))
        return aggregate_results(state)

    with patch("reviewguard.orchestration.graph.aggregate_results", side_effect=aggregate):
        graph = build_review_graph(
            code_quality=lambda f, s: review(AgentType.code_quality, f, s),
            security=lambda f, s: review(AgentType.security, f, s),
            test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw),
        )
        output = asyncio.run(graph.ainvoke(initial))
    assert len(finished) == 3 and len(snapshots) == 1
    assert set(output["agent_results"]) == set(AgentType)
    assert all(output["agent_results"][agent] == result(agent) for agent in AgentType)
    assert output["workflow_status"] == "completed"
    assert output["consolidated_report"]["findings"] == []
    assert len(output["consolidated_report"]["agent_statuses"]) == 3
    assert initial == original


def test_reducer_is_order_independent_and_does_not_mutate_inputs() -> None:
    updates = [{agent: result(agent)} for agent in AgentType]
    for order in permutations(updates):
        merged = {}
        for update in order:
            before = deepcopy(merged)
            merged = merge_agent_results(merged, update)
            assert all(merged[key] == value for key, value in before.items())
        assert set(merged) == set(AgentType)
    security_input = next(update[AgentType.security] for update in updates if AgentType.security in update)
    assert merged[AgentType.security] is not security_input
    merged[AgentType.security].status = "failed"
    assert security_input.status == "success"
    assert all(update == {key: result(key) for key in update} for update in updates)


def test_conflicting_result_is_rejected_without_overwrite() -> None:
    left = {AgentType.security: result(AgentType.security)}
    with pytest.raises(ValueError, match="duplicate"):
        merge_agent_results(left, left)
    with pytest.raises(ValueError, match="Conflicting"):
        merge_agent_results(left, {AgentType.security: result(AgentType.security, "failed")})
    assert left[AgentType.security].status == "success"
    with pytest.raises(ValueError, match="key"):
        merge_agent_results({}, {AgentType.security: result(AgentType.code_quality)})


def test_branch_failure_does_not_drop_other_results_or_retry() -> None:
    calls = []

    def fail(filename, source):
        calls.append("security")
        raise RuntimeError("PRIVATE_PROVIDER_DETAILS")

    graph = build_review_graph(code_quality=lambda f, s: result(AgentType.code_quality), security=fail,
        test_coverage=lambda f, s, **kw: result(AgentType.test_coverage))
    output = asyncio.run(graph.ainvoke(create_initial_state("x.py", "pass")))
    assert set(output["agent_results"]) == set(AgentType)
    assert output["workflow_status"] == "partial"
    assert output["agent_results"][AgentType.security].status == "failed"
    assert "PRIVATE" not in output["agent_results"][AgentType.security].error_message
    assert calls == ["security"]


def test_repeated_invocations_have_fresh_request_state() -> None:
    graph = build_review_graph(code_quality=lambda f, s: result(AgentType.code_quality),
        security=lambda f, s: result(AgentType.security), test_coverage=lambda f, s, **kw: result(AgentType.test_coverage))
    first = asyncio.run(graph.ainvoke(create_initial_state("one.py", "pass")))
    second = asyncio.run(graph.ainvoke(create_initial_state("two.py", "pass")))
    assert first["filename"] == "one.py" and second["filename"] == "two.py"
    assert first["agent_results"] is not second["agent_results"]


def test_branches_emit_only_their_own_result_updates() -> None:
    graph = build_review_graph(code_quality=lambda f, s: result(AgentType.code_quality),
        security=lambda f, s: result(AgentType.security), test_coverage=lambda f, s, **kw: result(AgentType.test_coverage))

    async def collect():
        return [update async for update in graph.astream(create_initial_state("x.py", "pass"), stream_mode="updates")]

    updates = asyncio.run(collect())
    expected = {"code_quality_node": AgentType.code_quality, "security_node": AgentType.security,
                "test_coverage_node": AgentType.test_coverage}
    for name, agent in expected.items():
        matches = [update[name] for update in updates if name in update]
        assert len(matches) == 1
        assert set(matches[0]) == {"agent_results"}
        assert set(matches[0]["agent_results"]) == {agent}
    assert sum("aggregation" in update for update in updates) == 1
