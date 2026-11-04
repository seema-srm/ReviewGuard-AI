"""Real agent implementations in LangGraph, with isolated mocked SDK clients."""

import asyncio
from contextlib import ExitStack
from copy import deepcopy
from itertools import permutations
import json
import logging
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from reviewguard.orchestration.graph import aggregate_results, build_review_graph
from reviewguard.orchestration.state import create_initial_state, merge_agent_results
from reviewguard.schemas import AgentReviewResult, AgentType


@pytest.mark.parametrize("order", list(permutations(tuple(AgentType))))
def test_real_agents_overlap_and_isolate_concurrent_workflows(order, caplog) -> None:
    barrier = Barrier(6, timeout=10)
    lock = Lock()
    filenames = ("first.py", "second.py")
    done = {filename: {agent: Event() for agent in AgentType} for filename in filenames}
    started, finished, clients, snapshots = [], [], [], []
    previous_logging = logging.root.manager.disable

    def factory(agent):
        client = Mock()
        client.with_options.return_value = client
        with lock:
            clients.append((agent, client))

        def complete(**kwargs):
            data = json.loads(kwargs["messages"][1]["content"])
            filename = data["filename"]
            assert data["source"] == f"# {filename}\npass\n"
            assert kwargs["max_tokens"] == (4096 if agent == AgentType.test_coverage else 2048)
            assert kwargs["response_format"] == {"type": "json_object"}
            if agent == AgentType.test_coverage:
                assert data["existing_tests"] == {"test_local.py": f"# {filename}"}
            with lock:
                started.append((filename, agent))
            barrier.wait()  # All six actual reviewer calls start before any completes.
            assert len(started) == 6
            assert logging.root.manager.disable == previous_logging
            logging.getLogger("reviewguard.application").warning("APPLICATION_VISIBLE")
            if agent == AgentType.code_quality:
                logging.getLogger("openai._base_client").critical("PRIVATE_QUALITY_SOURCE")
            else:
                logging.getLogger("openai._base_client").warning(f"VISIBLE_{agent.value}")
            index = order.index(agent)
            if index:
                assert done[filename][order[index - 1]].wait(10)
            with lock:
                finished.append((filename, agent))
            done[filename][agent].set()
            payload = {"agent": agent.value, "status": "success", "findings": []}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload)))])

        client.chat.completions.create.side_effect = complete
        return client

    def aggregate(state):
        assert all(event.is_set() for event in done[state["filename"]].values())
        assert set(state["agent_results"]) == set(AgentType)
        with lock:
            snapshots.append(deepcopy(state))
        return aggregate_results(state)

    modules = {AgentType.code_quality: "code_quality", AgentType.security: "security", AgentType.test_coverage: "test_coverage"}
    with ExitStack() as stack:
        # No SDK transport is allowed, even if the graph wiring regresses.
        transport = stack.enter_context(patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")))
        for agent, module in modules.items():
            stack.enter_context(patch(f"reviewguard.agents.{module}.load_fireworks_settings", return_value=SimpleNamespace(model="mock-model")))
            stack.enter_context(patch(f"reviewguard.agents.{module}.create_fireworks_client", side_effect=lambda settings, agent=agent: factory(agent)))
        stack.enter_context(patch("reviewguard.orchestration.graph.aggregate_results", side_effect=aggregate))
        graph = build_review_graph()  # Default nodes invoke real reviewer classes.
        assert clients == []
        inputs = [create_initial_state(filename, f"# {filename}\npass\n",
                   existing_tests={"test_local.py": f"# {filename}"}) for filename in filenames]
        originals = deepcopy(inputs)

        async def run():
            return await asyncio.gather(*(graph.ainvoke(state) for state in inputs))

        outputs = asyncio.run(run())
        transport.assert_not_called()
    assert len(clients) == 6 and len({id(client) for _, client in clients}) == 6
    assert len(snapshots) == 2
    for filename, output in zip(filenames, outputs):
        assert output["filename"] == filename
        assert output["workflow_status"] == "completed"
        assert output["consolidated_report"]["findings"] == []
        assert len(output["consolidated_report"]["agent_statuses"]) == 3
        assert [agent for name, agent in finished if name == filename] == list(order)
        assert set(output["agent_results"]) == set(AgentType)
        assert all(item.status == "success" for item in output["agent_results"].values())
    assert inputs == originals
    assert outputs[0]["agent_results"] is not outputs[1]["agent_results"]
    for _, client in clients:
        client.with_options.assert_called_once_with(timeout=30.0, max_retries=0)
        client.chat.completions.create.assert_called_once()
        client.close.assert_called_once()
    assert logging.root.manager.disable == previous_logging
    assert "PRIVATE_QUALITY_SOURCE" not in caplog.text
    assert "APPLICATION_VISIBLE" in caplog.text
    assert "VISIBLE_security" in caplog.text and "VISIBLE_test_coverage" in caplog.text


def test_identical_duplicate_result_is_rejected() -> None:
    value = AgentReviewResult(agent=AgentType.security, status="success", findings=[])
    left = {AgentType.security: value}
    with pytest.raises(ValueError, match="duplicate"):
        merge_agent_results(left, {AgentType.security: value.model_copy(deep=True)})
    assert left == {AgentType.security: value}


def test_sdk_filter_is_nested_and_restores_context_after_exception(caplog) -> None:
    from reviewguard.logging_safety import suppress_sdk_logging
    sdk = logging.getLogger("openai._base_client")
    app = logging.getLogger("reviewguard.application")
    before = (logging.root.manager.disable, sdk.level, tuple(sdk.handlers))
    with pytest.raises(RuntimeError):
        with suppress_sdk_logging():
            with suppress_sdk_logging():
                sdk.critical("PRIVATE_NESTED")
                app.warning("APP_NESTED_VISIBLE")
            sdk.critical("PRIVATE_OUTER")
            raise RuntimeError("test")
    sdk.warning("SDK_RESTORED")
    assert "PRIVATE_" not in caplog.text
    assert "APP_NESTED_VISIBLE" in caplog.text and "SDK_RESTORED" in caplog.text
    assert before == (logging.root.manager.disable, sdk.level, tuple(sdk.handlers))
