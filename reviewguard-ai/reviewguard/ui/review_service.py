"""Synchronous, loop-isolated entry point to the existing LangGraph workflow."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Any

from langfuse.langchain import CallbackHandler
from langsmith import tracing_context

from reviewguard.file_utils import ValidatedFile
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.langfuse_client import (
    create_langfuse_client,
    load_langfuse_settings,
    use_langfuse_client,
)
from reviewguard.orchestration.graph import build_review_graph
from reviewguard.orchestration.state import create_initial_state
from reviewguard.reports.models import ReviewReport


def run_review(
    upload: ValidatedFile,
    *,
    existing_tests: dict[str, str] | None = None,
    measured_coverage: dict[str, object] | None = None,
    tracing_enabled: bool | None = None,
    langfuse_tracing_enabled: bool | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> ReviewReport:
    """One workflow, no retries. Caller must require explicit submission.

    A dedicated worker owns the event loop, even if the caller has an active loop.
    No source, credentials or provider errors are logged. Exceptions are handled
    by the UI with fixed messages. Graph state is not cached; the Langfuse SDK
    manages its client lifecycle when tracing is explicitly enabled.
    """
    if tracing_enabled is None:
        tracing_enabled = os.getenv("REVIEWGUARD_LANGSMITH_TRACING", "").lower() in {
            "1", "true", "yes",
        }
    langfuse_settings = load_langfuse_settings(langfuse_tracing_enabled)

    def execute() -> ReviewReport:
        if tracing_enabled and not (
            os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        ):
            raise ValueError("LangSmith tracing is enabled but no API key is configured")
        load_fireworks_settings()  # Fail before inference if configuration is absent.
        project_name = os.getenv("LANGSMITH_PROJECT", "reviewguard")
        langfuse_client = (
            create_langfuse_client(langfuse_settings)
            if langfuse_settings is not None
            else None
        )
        langfuse_handler = (
            CallbackHandler(public_key=langfuse_settings.public_key)
            if langfuse_settings is not None
            else None
        )
        with tracing_context(
            enabled=tracing_enabled,
            project_name=project_name if tracing_enabled else None,
            metadata=trace_metadata if tracing_enabled else None,
        ):
            graph = build_review_graph()
            config: dict[str, Any] = {}
            if trace_metadata and (tracing_enabled or langfuse_handler is not None):
                config["metadata"] = trace_metadata
            if langfuse_handler is not None:
                config["callbacks"] = [langfuse_handler]
            client_context = (
                use_langfuse_client(langfuse_client)
                if langfuse_client is not None
                else nullcontext()
            )
            try:
                with client_context:
                    output = asyncio.run(
                        graph.ainvoke(
                            create_initial_state(
                                upload.filename,
                                upload.source,
                                existing_tests=existing_tests,
                                measured_coverage=measured_coverage,
                            ),
                            config=config or None,
                        )
                    )
            finally:
                if langfuse_client is not None:
                    try:
                        langfuse_client.flush()
                    except Exception:
                        # Telemetry delivery must not discard a completed report or
                        # replace the original workflow exception with an SDK error.
                        pass
            report = ReviewReport.model_validate(output["consolidated_report"])
            if report.filename != upload.filename or report.workflow_status != output["workflow_status"]:
                raise ValueError("Workflow report does not match request")
            return report

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result()
