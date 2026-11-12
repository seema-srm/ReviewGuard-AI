"""Replay reviewed cases through coverage only; never retry or retain rejected text."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langsmith import tracing_context

from reviewguard.agents.test_coverage import TestCoverageReviewer, SYSTEM_PROMPT
from reviewguard.evals.runner import read_cases, validate_reviewed_cases
from reviewguard.fireworks_client import load_fireworks_settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--failed-only", action="store_true")
    parser.add_argument("--confirm-paid-runs", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_paid_runs:
        parser.error("Pass --confirm-paid-runs for one paid coverage request per selected case")
    logging.disable(logging.CRITICAL)
    cases = read_cases(args.dataset)
    validate_reviewed_cases(cases)
    baseline = [json.loads(line) for line in args.baseline.read_text(encoding="utf-8").splitlines()]
    failed = {row["case_id"] for row in baseline if any(
        s["agent"] == "test_coverage" and s["status"] != "success"
        for s in row["report"]["agent_statuses"])}
    if args.failed_only:
        cases = [case for case in cases if case.case_id in failed]
    settings = load_fireworks_settings()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.output.open("x", encoding="utf-8") as stream, tracing_context(enabled=False):
        for case in cases:
            reviewer = TestCoverageReviewer()
            started = time.perf_counter()
            started_at = datetime.now(timezone.utc).isoformat()
            result = reviewer.review(case.filename, case.source, existing_tests=case.existing_tests,
                                     measured_coverage=case.measured_coverage)
            row = {
                "case_id": case.case_id,
                "started_at_utc": started_at,
                "model": settings.model,
                "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                "reviewer_sha256": hashlib.sha256(
                    (Path(__file__).resolve().parents[1] / "reviewguard/agents/test_coverage.py").read_bytes()
                ).hexdigest(),
                "latency_seconds": time.perf_counter() - started,
                "completion": asdict(reviewer.last_completion_metadata),
                "validation": asdict(reviewer.last_validation_diagnostics),
                "result": result.model_dump(mode="json"),
            }
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            rows.append(row)
            print(f"{len(rows)}/{len(cases)} {case.case_id}: {result.status}; "
                  f"stage={reviewer.last_validation_diagnostics.stage}", flush=True)
    summary = {
        "cases": len(rows), "successes": sum(row["result"]["status"] == "success" for row in rows),
        "failure_stages": dict(Counter(row["validation"]["stage"] for row in rows
                                       if row["result"]["status"] != "success")),
    }
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
