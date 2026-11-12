"""Save each baseline result locally; live inference requires an explicit CLI flag."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time

from reviewguard.evals.runner import read_cases, validate_reviewed_cases
from reviewguard.evals.scoring import score_review
from reviewguard.file_utils import validate_python_file
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.ui.review_service import run_review


def summarize(rows):
    groups = {}
    for target in ["all", "code_quality", "security", "test_coverage"]:
        selected = [r for r in rows if target == "all" or r["target_agent"] == target]
        if not selected:
            continue
        groups[target] = {
            "cases": len(selected),
            "target_successes": sum(r["target_status"] == "success" for r in selected),
            "completed_workflows": sum(r["workflow_status"] == "completed" for r in selected),
            "macro_scores": {key: sum(r["scores"][key] for r in selected) / len(selected)
                             for key in selected[0]["scores"]},
            "mean_latency_seconds": sum(r["latency_seconds"] for r in selected) / len(selected),
            "failure_categories": dict(Counter(r["error_category"] for r in selected
                                               if r["target_status"] != "success")),
        }
    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-paid-runs", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_paid_runs:
        parser.error("Pass --confirm-paid-runs to authorize up to three paid calls per case")
    logging.disable(logging.CRITICAL)
    cases = read_cases(args.dataset)
    validate_reviewed_cases(cases)
    settings = load_fireworks_settings()
    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement or a duplicate paid run.
    with args.output.open("x", encoding="utf-8") as stream:
        rows = []
        for case in cases:
            start = time.perf_counter()
            started_at = datetime.now(timezone.utc).isoformat()
            report_data = None
            try:
                report = run_review(
                    validate_python_file(case.filename, case.source.encode("utf-8")),
                    existing_tests=case.existing_tests,
                    measured_coverage=case.measured_coverage,
                    tracing_enabled=False, langfuse_tracing_enabled=False,
                )
                report_data = report.model_dump(mode="json")
            except Exception:
                pass  # Record a sanitized failed case; never retry inference.
            statuses = {s["agent"]: s for s in (report_data or {}).get("agent_statuses", [])}
            status = statuses.get(case.target_agent.value, {})
            row = {
                "case_id": case.case_id, "scenario_type": case.scenario_type,
                "target_agent": case.target_agent.value,
                "dataset_sha256": dataset_hash, "model": settings.model,
                "started_at_utc": started_at,
                "latency_seconds": time.perf_counter() - start,
                "target_status": status.get("status", "failed"),
                "workflow_status": (report_data or {}).get("workflow_status", "failed"),
                "error_category": status.get("error_category") or
                    ("none" if status.get("status") == "success" else "execution_error"),
                "reference": {"expected_findings": [f.model_dump(mode="json")
                                                     for f in case.expected_findings]},
                "report": report_data,
            }
            row["scores"] = score_review(report_data, row["reference"],
                                         target_agent=case.target_agent.value)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            rows.append(row)
            print(f"{len(rows)}/{len(cases)} {case.case_id}: {row['target_status']}; "
                  f"anchor F1={row['scores']['finding_f1']:.3f}", flush=True)
    summary = summarize(rows)
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
