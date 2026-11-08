"""Publish adjudicated cases and evaluate the live pipeline in LangSmith."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langsmith import Client

from reviewguard.evals.models import EvaluationCase
from reviewguard.evals.scoring import langsmith_evaluator
from reviewguard.file_utils import validate_python_file
from reviewguard.fireworks_client import load_fireworks_settings
from reviewguard.ui.review_service import run_review

MIN_CASES = 30
MAX_CASES = 50


def read_cases(path: Path) -> list[EvaluationCase]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(EvaluationCase.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"Invalid evaluation case on line {line_number}") from exc
    if not MIN_CASES <= len(cases) <= MAX_CASES:
        raise ValueError(f"Dataset must contain {MIN_CASES}-{MAX_CASES} cases; found {len(cases)}")
    ids = [case.case_id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Evaluation case IDs must be unique")
    return cases


def validate_reviewed_cases(cases: list[EvaluationCase]) -> None:
    if not MIN_CASES <= len(cases) <= MAX_CASES:
        raise ValueError(f"Dataset must contain {MIN_CASES}-{MAX_CASES} cases; found {len(cases)}")
    pending = [case.case_id for case in cases if case.annotation_status != "reviewed"]
    if pending:
        preview = ", ".join(pending[:5])
        raise ValueError(
            f"{len(pending)} cases still need human review ({preview}). "
            "Do not report evaluation metrics until every case is reviewed."
        )
    if any(not (case.reviewer_notes or "").strip() for case in cases):
        raise ValueError("Every reviewed case requires reviewer_notes describing the adjudication")


def upload_dataset(client: Client, dataset_name: str, cases: list[EvaluationCase]) -> None:
    validate_reviewed_cases(cases)
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Human-reviewed ReviewGuard AI evaluation cases.",
        metadata={"case_count": len(cases), "ground_truth": "human-reviewed"},
    )
    for case in cases:
        client.create_example(
            dataset_id=dataset.id,
            inputs={
                "case_id": case.case_id,
                "filename": case.filename,
                "source": case.source,
                "target_agent": case.target_agent.value,
                "existing_tests": case.existing_tests,
                "measured_coverage": case.measured_coverage,
            },
            outputs={
                "expected_findings": [
                    item.model_dump(mode="json") for item in case.expected_findings
                ],
            },
            metadata={
                "scenario_type": case.scenario_type,
                "reviewer": case.reviewer,
                "reviewer_notes": case.reviewer_notes,
            },
        )


def evaluate_dataset(
    client: Client,
    dataset_name: str,
    experiment_prefix: str,
) -> Any:
    settings = load_fireworks_settings()

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        upload = validate_python_file(inputs["filename"], inputs["source"].encode("utf-8"))
        report = run_review(
            upload,
            existing_tests=inputs.get("existing_tests"),
            measured_coverage=inputs.get("measured_coverage"),
            tracing_enabled=True,
            trace_metadata={
                "evaluation_case_id": inputs["case_id"],
                "target_agent": inputs["target_agent"],
                "evaluation_dataset": dataset_name,
                "model": settings.model,
            },
        )
        return {"report": report.model_dump(mode="json")}

    return client.evaluate(
        target,
        data=dataset_name,
        evaluators=[langsmith_evaluator],
        experiment_prefix=experiment_prefix,
        description="ReviewGuard full three-agent evaluation; one model call per agent per case.",
        metadata={
            "dataset": dataset_name,
            "model": settings.model,
            "reviewguard_version": "1",
        },
        max_concurrency=1,
        blocking=True,
    )


def require_live_evaluation_authorization() -> None:
    if os.getenv("REVIEWGUARD_LANGSMITH_TRACING", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("Set REVIEWGUARD_LANGSMITH_TRACING=true to explicitly enable source-code tracing")
    if not (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        raise ValueError("Set LANGSMITH_API_KEY in the process environment; its value is never printed")
    if os.getenv("REVIEWGUARD_ALLOW_PAID_EVAL", "").lower() not in {"1", "true", "yes"}:
        raise ValueError("Set REVIEWGUARD_ALLOW_PAID_EVAL=true to authorize Fireworks evaluation requests")
