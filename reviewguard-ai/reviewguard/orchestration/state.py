"""Typed request state and pure parallel-result merging."""

from copy import deepcopy
from typing import Annotated, Literal, TypedDict

from reviewguard.schemas import AgentReviewResult, AgentType

AgentResults = dict[AgentType, AgentReviewResult]


def merge_agent_results(left: AgentResults, right: AgentResults) -> AgentResults:
    """Merge independent branches without mutation or silent conflicting writes.

    All duplicate agent keys fail, including identical repeated results,
    rather than allowing execution order to choose a winner. Copies prevent
    mutable Pydantic findings from aliasing the input snapshots.
    """
    merged = deepcopy(left)
    for agent, result in right.items():
        if result.agent != agent:
            raise ValueError("Result key must match result agent")
        if agent in merged:
            raise ValueError("Conflicting duplicate results for the same agent")
        merged[agent] = result.model_copy(deep=True)
    return merged


class ReviewState(TypedDict):
    filename: str
    source_code: str
    existing_tests: dict[str, str] | None
    measured_coverage: dict[str, object] | None
    agent_results: Annotated[AgentResults, merge_agent_results]
    consolidated_report: dict[str, object] | None
    workflow_status: Literal["ready", "completed", "partial", "failed"]


def create_initial_state(
    filename: str, source_code: str, *,
    existing_tests: dict[str, str] | None = None,
    measured_coverage: dict[str, object] | None = None,
) -> ReviewState:
    """Create fresh state for each invocation; inputs must already be validated."""
    return ReviewState(
        filename=filename, source_code=source_code,
        existing_tests=deepcopy(existing_tests), measured_coverage=deepcopy(measured_coverage),
        agent_results={}, consolidated_report=None, workflow_status="ready",
    )
