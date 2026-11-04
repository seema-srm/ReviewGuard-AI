"""Three concurrent review branches followed by a single aggregation barrier."""

import asyncio
import json
from copy import deepcopy
from typing import Callable, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from reviewguard.agents.code_quality import CodeQualityReviewer
from reviewguard.agents.security import SecurityReviewer
from reviewguard.agents.test_coverage import TestCoverageReviewer
from reviewguard.orchestration.state import ReviewState
from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.reports.builder import build_review_report
from reviewguard.reports.export import export_report_json
from reviewguard.schemas import AgentReviewResult, AgentType, ErrorCategory, SourceValidationError, normalize_error_category, validate_finding_against_source

ReviewCallable = Callable[[str, str], AgentReviewResult]


class CoverageCallable(Protocol):
    def __call__(self, filename: str, source: str, *,
                 existing_tests: dict[str, str] | None = None,
                 measured_coverage: dict[str, object] | None = None) -> AgentReviewResult: ...


def aggregate_results(state: ReviewState) -> dict[str, object]:
    """Deduplicate and prioritize structured findings; formatting comes later."""
    results = state["agent_results"]
    if set(results) != set(AgentType):
        raise ValueError("Aggregation requires explicit results from all three agents")
    aggregation = aggregate_findings(results, sources={state["filename"]: state["source_code"]})
    report = build_review_report(aggregation, filename=state["filename"])
    return {"workflow_status": report.workflow_status, "consolidated_report": json.loads(export_report_json(report))}


def build_review_graph(
    *, code_quality: ReviewCallable | None = None,
    security: ReviewCallable | None = None,
    test_coverage: CoverageCallable | None = None,
) -> CompiledStateGraph:
    """Compile without configuration reads or API calls. Use graph.ainvoke(state).

    Inject synchronous callables for offline tests. Default reviewers are created
    inside their worker threads per invocation, avoiding shared reviewer metadata.
    No retry policy, persistence, tracing setup, or report formatting is added.
    """
    def run_agent(agent: AgentType, state: ReviewState) -> AgentReviewResult:
        try:
            filename, source = state["filename"], state["source_code"]
            if agent == AgentType.code_quality:
                result = (code_quality if code_quality is not None else CodeQualityReviewer().review)(filename, source)
            elif agent == AgentType.security:
                result = (security if security is not None else SecurityReviewer().review)(filename, source)
            else:
                reviewer = test_coverage if test_coverage is not None else TestCoverageReviewer().review
                result = reviewer(filename, source, existing_tests=deepcopy(state.get("existing_tests")),
                                  measured_coverage=deepcopy(state.get("measured_coverage")))
            # Revalidate even Pydantic instances; do not trust injected results.
            if not isinstance(result, AgentReviewResult):
                return AgentReviewResult(agent=agent, status="failed", findings=[],
                    error_message="Agent returned an invalid review result; details suppressed.", error_category=ErrorCategory.invalid_schema)
            result = AgentReviewResult.model_validate(result.model_dump())
            if result.agent != agent:
                return AgentReviewResult(agent=agent, status="failed", findings=[],
                    error_message="Agent returned the wrong result type; details suppressed.", error_category=ErrorCategory.invalid_schema)
            if result.status != "success":
                # Injected callables may return sensitive exception text as metadata.
                # Keep their explicit status but never propagate arbitrary error bodies.
                return AgentReviewResult(agent=agent, status=result.status, findings=[], error_category=normalize_error_category(result.error_category),
                    error_message="Agent review failed; details suppressed." if result.status == "failed"
                    else "Agent review skipped; details suppressed.")
            for finding in result.findings:
                validate_finding_against_source(finding, source, filename=filename)
            return result
        except (TimeoutError, APITimeoutError):
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                                     error_message="Agent request timed out; no automatic retry attempted.", error_category=ErrorCategory.api_timeout)
        except SourceValidationError:
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                error_message="Agent returned unsupported source evidence; details suppressed.", error_category=ErrorCategory.invalid_source_evidence)
        except json.JSONDecodeError:
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                error_message="Agent returned invalid JSON; details suppressed.", error_category=ErrorCategory.invalid_json)
        except ValidationError:
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                                     error_message="Agent returned an invalid review result; details suppressed.", error_category=ErrorCategory.invalid_schema)
        except (APIConnectionError, APIStatusError):
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                error_message="Agent provider request failed; details suppressed.", error_category=ErrorCategory.provider_error)
        except Exception:
            return AgentReviewResult(agent=agent, status="failed", findings=[],
                                     error_message="Review branch failed; provider details suppressed.", error_category=ErrorCategory.unknown_error)

    async def code_quality_node(state: ReviewState) -> dict[str, object]:
        result = await asyncio.to_thread(run_agent, AgentType.code_quality, state)
        return {"agent_results": {AgentType.code_quality: result}}

    async def security_node(state: ReviewState) -> dict[str, object]:
        result = await asyncio.to_thread(run_agent, AgentType.security, state)
        return {"agent_results": {AgentType.security: result}}

    async def test_coverage_node(state: ReviewState) -> dict[str, object]:
        result = await asyncio.to_thread(run_agent, AgentType.test_coverage, state)
        return {"agent_results": {AgentType.test_coverage: result}}

    graph = StateGraph(ReviewState)
    graph.add_node("code_quality_node", code_quality_node)
    graph.add_node("security_node", security_node)
    graph.add_node("test_coverage_node", test_coverage_node)
    graph.add_node("aggregation", aggregate_results)
    branches = ["code_quality_node", "security_node", "test_coverage_node"]
    for branch in branches:
        graph.add_edge(START, branch)
    graph.add_edge(branches, "aggregation")
    graph.add_edge("aggregation", END)
    return graph.compile()
