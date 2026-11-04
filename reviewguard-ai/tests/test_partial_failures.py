"""Offline partial-failure, grounding and isolation tests for the workflow."""

import asyncio
from copy import deepcopy
from itertools import permutations, product
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import APITimeoutError
import pytest

from reviewguard.agents.security import SecurityReviewer
from reviewguard.orchestration.graph import aggregate_results, build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.schemas import AgentReviewResult, AgentType, ReviewFinding


def review_result(agent, status="success", filename="example.py", with_finding=True):
    findings = []
    if status == "success" and with_finding:
        findings = [ReviewFinding(
            finding_id=f"{agent.value}-1", agent=agent, title="Test finding",
            category="recommended_test", severity="LOW", filename=filename,
            line_number=1, description="Synthetic offline test fixture.", evidence="pass",
            recommendation="Check behavior.", confidence=0.8,
            suggested_tests=["test_case: input=1; expected=1"],
        )]
    return AgentReviewResult(agent=agent, status=status, findings=findings,
        error_message="PRIVATE_KEY_SOURCE_PROVIDER_BODY" if status != "success" else None)


@pytest.mark.parametrize("statuses", list(product(("success", "failed", "skipped"), repeat=3)))
def test_status_combinations_preserve_successful_findings(statuses, caplog, capsys) -> None:
    expected_results = {agent: review_result(agent, status) for agent, status in zip(AgentType, statuses)}
    graph = build_review_graph(code_quality=lambda f, s: expected_results[AgentType.code_quality],
        security=lambda f, s: expected_results[AgentType.security],
        test_coverage=lambda f, s, **kw: expected_results[AgentType.test_coverage])
    state = create_initial_state("example.py", "pass\n")
    original = deepcopy(state)
    output = asyncio.run(graph.ainvoke(state))
    successes = statuses.count("success")
    assert output["workflow_status"] == ("completed" if successes == 3 else "partial" if successes else "failed")
    assert set(output["agent_results"]) == set(AgentType)
    assert state == original
    assert output["consolidated_report"]["workflow_status"] == output["workflow_status"]
    assert len(output["consolidated_report"]["agent_statuses"]) == 3
    for agent, status in zip(AgentType, statuses):
        actual = output["agent_results"][agent]
        assert actual.status == status
        assert actual.findings == (expected_results[agent].findings if status == "success" else [])
        if status != "success":
            assert actual.error_message and "PRIVATE" not in actual.error_message
    assert "PRIVATE" not in caplog.text + capsys.readouterr().out


def test_successful_empty_review_is_success_not_failure() -> None:
    graph = build_review_graph(code_quality=lambda f, s: review_result(AgentType.code_quality, with_finding=False),
        security=lambda f, s: review_result(AgentType.security, "failed"),
        test_coverage=lambda f, s, **kw: review_result(AgentType.test_coverage, "skipped"))
    output = asyncio.run(graph.ainvoke(create_initial_state("example.py", "pass")))
    assert output["workflow_status"] == "partial"
    clean = output["agent_results"][AgentType.code_quality]
    assert clean.status == "success" and clean.findings == [] and clean.error_message is None
    assert output["agent_results"][AgentType.security].status == "failed"


@pytest.mark.parametrize("order", list(permutations(tuple(AgentType))))
def test_failure_completion_orders_and_barrier_once(order) -> None:
    barrier = Barrier(3, timeout=5)
    events = {agent: Event() for agent in AgentType}
    finished = []
    snapshots = []

    def review(agent, filename, source, **kwargs):
        barrier.wait()
        index = order.index(agent)
        if index:
            assert events[order[index - 1]].wait(5)
        finished.append(agent)
        events[agent].set()
        if agent == AgentType.security:
            raise RuntimeError("PRIVATE_PROVIDER_BODY")
        return review_result(agent)

    def aggregate(state):
        assert len(finished) == 3 and set(state["agent_results"]) == set(AgentType)
        snapshots.append(deepcopy(state))
        return aggregate_results(state)

    with patch("reviewguard.orchestration.graph.aggregate_results", side_effect=aggregate):
        graph = build_review_graph(code_quality=lambda f, s: review(AgentType.code_quality, f, s),
            security=lambda f, s: review(AgentType.security, f, s),
            test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw))
        output = asyncio.run(graph.ainvoke(create_initial_state("example.py", "pass")))
    assert finished == list(order) and len(snapshots) == 1
    assert output["workflow_status"] == "partial"
    assert len(output["agent_results"][AgentType.code_quality].findings) == 1
    assert len(output["agent_results"][AgentType.test_coverage].findings) == 1
    assert output["agent_results"][AgentType.security].findings == []


@pytest.mark.parametrize("kind", ["timeout", "invalid_json"])
def test_real_reviewer_failure_preserves_siblings(kind) -> None:
    client = Mock()
    client.with_options.return_value = client
    if kind == "timeout":
        client.chat.completions.create.side_effect = APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
    else:
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="PRIVATE_INVALID_JSON"))])
    graph = build_review_graph(code_quality=lambda f, s: review_result(AgentType.code_quality),
        security=SecurityReviewer(client, "mock-model").review,
        test_coverage=lambda f, s, **kw: review_result(AgentType.test_coverage))
    with patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as transport:
        output = asyncio.run(graph.ainvoke(create_initial_state("example.py", "pass")))
    transport.assert_not_called()
    assert output["workflow_status"] == "partial"
    assert output["agent_results"][AgentType.security].status == "failed"
    assert not output["agent_results"][AgentType.security].findings
    assert len(output["agent_results"][AgentType.code_quality].findings) == 1
    assert len(output["agent_results"][AgentType.test_coverage].findings) == 1
    client.chat.completions.create.assert_called_once()
    client.with_options.assert_called_once_with(timeout=30.0, max_retries=0)


@pytest.mark.parametrize("kind", ["timeout", "exception", "invalid_result", "wrong_agent", "bad_evidence"])
def test_injected_failures_fail_closed(kind, caplog, capsys) -> None:
    def fail(filename, source):
        if kind == "timeout":
            raise TimeoutError("PRIVATE_KEY_SOURCE_PROVIDER_BODY")
        if kind == "exception":
            raise RuntimeError("PRIVATE_KEY_SOURCE_PROVIDER_BODY")
        if kind == "invalid_result":
            return {"PRIVATE_KEY": "PRIVATE_SOURCE"}
        if kind == "wrong_agent":
            return review_result(AgentType.code_quality)
        value = review_result(AgentType.security)
        value.findings[0].evidence = "PRIVATE_UNSUPPORTED_SOURCE"
        return value

    graph = build_review_graph(code_quality=lambda f, s: review_result(AgentType.code_quality), security=fail,
        test_coverage=lambda f, s, **kw: review_result(AgentType.test_coverage))
    output = asyncio.run(graph.ainvoke(create_initial_state("example.py", "pass")))
    assert output["workflow_status"] == "partial"
    failed = output["agent_results"][AgentType.security]
    assert failed.status == "failed" and failed.findings == []
    assert "PRIVATE" not in failed.model_dump_json() + caplog.text + capsys.readouterr().out


def test_concurrent_partial_requests_do_not_leak() -> None:
    barrier = Barrier(6, timeout=5)
    lock = Lock()
    calls = []

    def review(agent, filename, source, **kwargs):
        with lock:
            calls.append((filename, agent))
        barrier.wait()
        status = "failed" if filename == "bad.py" and agent == AgentType.security else "success"
        return review_result(agent, status, filename)

    graph = build_review_graph(code_quality=lambda f, s: review(AgentType.code_quality, f, s),
        security=lambda f, s: review(AgentType.security, f, s),
        test_coverage=lambda f, s, **kw: review(AgentType.test_coverage, f, s, **kw))
    states = [create_initial_state(filename, "pass") for filename in ("bad.py", "good.py")]
    originals = deepcopy(states)

    async def run():
        return await asyncio.gather(*(graph.ainvoke(state) for state in states))

    bad, good = asyncio.run(run())
    assert bad["workflow_status"] == "partial" and good["workflow_status"] == "completed"
    assert len(calls) == 6 and states == originals
    for output in (bad, good):
        for value in output["agent_results"].values():
            assert all(item.filename == output["filename"] for item in value.findings)
    assert good["agent_results"][AgentType.security].status == "success"
