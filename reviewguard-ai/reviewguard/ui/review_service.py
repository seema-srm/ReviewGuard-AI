"""Synchronous, loop-isolated entry point to the existing LangGraph workflow."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langsmith import tracing_context

from reviewguard.file_utils import ValidatedFile
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.models import ReviewReport


def run_review(
    upload: ValidatedFile,
    *,
    existing_tests: dict[str, str] | None = None,
    measured_coverage: dict[str, object] | None = None,
    tracing_enabled: bool | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> ReviewReport:
    """One workflow, no retries. Caller must require explicit submission.

    A dedicated worker owns the event loop, even if the caller has an active loop.
    No source, credentials or provider errors are logged. Exceptions are handled
    by the UI with fixed messages. No clients or mutable graph state are cached.
    """
    if tracing_enabled is None:
        tracing_enabled = os.getenv("REVIEWGUARD_LANGSMITH_TRACING", "").lower() in {
            "1", "true", "yes",
        }

    def execute() -> ReviewReport:
        if tracing_enabled and not (
            os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        ):
            raise ValueError("LangSmith tracing is enabled but no API key is configured")
        load_fireworks_settings()  # Fail before inference if configuration is absent.
        project_name = os.getenv("LANGSMITH_PROJECT", "reviewguard")
        with tracing_context(
            enabled=tracing_enabled,
            project_name=project_name if tracing_enabled else None,
            metadata=trace_metadata if tracing_enabled else None,
        ):
            graph = build_review_graph()
            output = asyncio.run(
                graph.ainvoke(
                    create_initial_state(
                        upload.filename,
                        upload.source,
                        existing_tests=existing_tests,
                        measured_coverage=measured_coverage,
                    ),
                    config={"metadata": trace_metadata or {}} if tracing_enabled else None,
                )
            )
            report = ReviewReport.model_validate(output["consolidated_report"])
            if report.filename != upload.filename or report.workflow_status != output["workflow_status"]:
                raise ValueError("Workflow report does not match request")
            return report

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result()
