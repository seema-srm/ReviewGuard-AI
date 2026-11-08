"""Synchronous, loop-isolated entry point to the existing LangGraph workflow."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from langsmith import tracing_context

from reviewguard.file_utils import ValidatedFile
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.models import ReviewReport


def run_review(upload: ValidatedFile) -> ReviewReport:
    """One workflow, no retries. Caller must require explicit submission.

    A dedicated worker owns the event loop, even if the caller has an active loop.
    No source, credentials or provider errors are logged. Exceptions are handled
    by the UI with fixed messages. No clients or mutable graph state are cached.
    """
    def execute() -> ReviewReport:
        load_fireworks_settings()  # Fail before inference if configuration is absent.
        with tracing_context(enabled=False):
            graph = build_review_graph()
            output = asyncio.run(graph.ainvoke(create_initial_state(upload.filename, upload.source)))
            report = ReviewReport.model_validate(output["consolidated_report"])
            if report.filename != upload.filename or report.workflow_status != output["workflow_status"]:
                raise ValueError("Workflow report does not match request")
            return report

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result()
