"""Explicit synthetic workflow diagnostic; up to three paid Fireworks requests."""

import argparse
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reviewguard.file_utils import validate_python_file
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.langfuse_client import create_langfuse_client, load_langfuse_settings
from reviewguard.ui.review_service import run_review

SOURCE = b"def total(values):\n    return sum(values[1:])\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_paid_run:
        print("No calls sent. Pass --confirm-paid-run for one synthetic three-agent review.")
        return 2

    # Diagnostics never print SDK logs, remote error bodies, source, or credentials.
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    client = None
    try:
        load_fireworks_settings()
        settings = load_langfuse_settings(True)
        client = create_langfuse_client(settings)
        stage = "Langfuse authentication"
        if not client.auth_check():
            print("Langfuse authentication: FAIL; no inference sent.")
            return 1
        print("Langfuse authentication: PASS", flush=True)
        trace_id = client.create_trace_id()
        print(f"Diagnostic trace ID: {trace_id}", flush=True)

        stage = "synthetic workflow"
        report = run_review(
            validate_python_file("langfuse_smoke.py", SOURCE),
            tracing_enabled=False,
            langfuse_tracing_enabled=True,
            langfuse_trace_id=trace_id,
            trace_metadata={"diagnostic": "langfuse-smoke"},
        )
        print(f"Workflow status: {report.workflow_status}", flush=True)
        for agent in report.agent_statuses:
            print(f"Agent {agent.agent.value}: {agent.status}", flush=True)

        stage = "trace ingestion"
        deadline = time.monotonic() + 45
        generations = []
        while time.monotonic() < deadline:
            observations = client.api.observations.get_many(
                trace_id=trace_id, fields="basic,model,usage,io", limit=100,
                request_options={"timeout_in_seconds": 5, "max_retries": 0},
            ).data
            generations = [o for o in observations if o.type == "GENERATION"]
            if len(generations) >= 3:
                break
            time.sleep(3)
        complete = (
            len(generations) == 3
            and all(o.input is not None and o.output is not None and o.usage_details
                    for o in generations)
        )
        print(f"Persisted generations: {len(generations)}/3")
        print("Prompts, outputs, and usage: " + ("PASS" if complete else "NOT VERIFIED"))
        return 0 if complete and report.workflow_status == "completed" else 1
    except Exception:
        print(f"Diagnostic failed during {stage}; details suppressed. No inference retry attempted.")
        return 1
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
