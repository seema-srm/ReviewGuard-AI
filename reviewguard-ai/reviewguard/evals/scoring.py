"""Finding-level metrics and LangSmith evaluator for reviewed cases."""

from datetime import datetime
from typing import Any


def _finding_rows(report: dict[str, Any], target_agent: str) -> list[dict[str, Any]]:
    rows = []
    for group in report.get("findings", []):
        originals = group.get("original_findings") or [group.get("representative", {})]
        rows.extend(item for item in originals if item.get("agent") == target_agent)
    return rows


def score_review(
    report: dict[str, Any] | None,
    reference: dict[str, Any],
    *,
    target_agent: str,
) -> dict[str, float]:
    """Match findings by target agent and exact source anchor; score severity separately."""
    expected = reference.get("expected_findings", [])
    status = next((item.get("status") for item in (report or {}).get("agent_statuses", [])
                   if item.get("agent") == target_agent), None)
    if status != "success":
        # A failed negative case is unavailable, not a correct clean review.
        return dict.fromkeys(("finding_precision", "finding_recall", "finding_f1",
                              "exact_match", "severity_accuracy"), 0.0)
    predicted = _finding_rows(report or {}, target_agent)
    matched: set[int] = set()
    severity_matches = 0
    for item in expected:
        for index, finding in enumerate(predicted):
            if index not in matched and item["anchor"] in finding.get("evidence", ""):
                matched.add(index)
                severity_matches += int(finding.get("severity") == item.get("severity"))
                break

    true_positives = len(matched)
    precision = true_positives / len(predicted) if predicted else float(not expected)
    recall = true_positives / len(expected) if expected else float(not predicted)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "finding_precision": precision,
        "finding_recall": recall,
        "finding_f1": f1,
        "exact_match": float(true_positives == len(expected) == len(predicted)),
        "severity_accuracy": severity_matches / true_positives if true_positives else 0.0,
    }


def _duration_ms(run: Any) -> float | None:
    start = getattr(run, "start_time", None)
    end = getattr(run, "end_time", None)
    if isinstance(start, datetime) and isinstance(end, datetime):
        return max(0.0, (end - start).total_seconds() * 1000)
    return None


def langsmith_evaluator(run: Any, example: Any) -> list[dict[str, Any]]:
    """Emit per-case quality, completion, latency and available usage measures."""
    inputs = example.inputs or {}
    outputs = run.outputs or {}
    report = outputs.get("report")
    reference = example.outputs or {}
    target_agent = inputs.get("target_agent", "")
    scores = score_review(report, reference, target_agent=target_agent)
    agent_statuses = {
        item.get("agent"): item
        for item in (report or {}).get("agent_statuses", [])
    }
    target_status = agent_statuses.get(target_agent, {})
    scores["target_agent_success"] = float(target_status.get("status") == "success")
    scores["workflow_completion"] = float((report or {}).get("workflow_status") == "completed")
    latency = _duration_ms(run)
    if latency is not None:
        scores["latency_ms"] = latency
    for field in ("prompt_tokens", "completion_tokens", "total_tokens", "total_cost"):
        value = getattr(run, field, None)
        if isinstance(value, (int, float)) and value >= 0:
            scores["cost_usd" if field == "total_cost" else field] = float(value)

    expected = reference.get("expected_findings", [])
    predicted = _finding_rows(report or {}, target_agent)
    matched_anchors = [
        item["anchor"]
        for item in expected
        if any(item["anchor"] in finding.get("evidence", "") for finding in predicted)
    ]
    missed = [
        item["label"]
        for item in expected
        if item["anchor"] not in matched_anchors
    ]
    failure_category = target_status.get("error_category") or "none"
    comment = (
        f"target={target_agent}; missed={','.join(missed) or 'none'}; "
        f"extra_findings={max(0, len(predicted) - len(matched_anchors))}; "
        f"failure_category={failure_category}"
    )
    result = []
    for key, value in scores.items():
        item = {"key": key, "score": value}
        if key in {"finding_f1", "target_agent_success"}:
            item["comment"] = comment
        result.append(item)
    result.append({"key": "failure_category", "value": failure_category})
    return result
