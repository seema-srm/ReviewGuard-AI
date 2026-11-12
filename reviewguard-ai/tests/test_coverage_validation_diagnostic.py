"""Paid coverage replays require an explicit flag and never retry a failed result."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import check_coverage_validation as diagnostic
from reviewguard.agents.test_coverage import CompletionMetadata, ValidationDiagnostics
from reviewguard.evals.models import EvaluationCase
from reviewguard.schemas import AgentReviewResult


def test_no_paid_flag_loads_no_configuration():
    with patch.object(diagnostic, "load_fireworks_settings") as settings, pytest.raises(SystemExit):
        diagnostic.main(["--dataset", "unused", "--baseline", "unused", "--output", "unused"])
    settings.assert_not_called()


def test_failed_only_selection_persists_diagnostics_and_refuses_overwrite(tmp_path):
    cases = [EvaluationCase(case_id=name, scenario_type="fixture", annotation_status="reviewed",
                            reviewer="offline", reviewer_notes="fixture", target_agent="security",
                            filename=name + ".py", source="pass\n", expected_findings=[])
             for name in ["failed", "completed"]]
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("\n".join(case.model_dump_json() for case in cases), encoding="utf-8")
    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text("\n".join(json.dumps({"case_id": name, "report": {"agent_statuses": [
        {"agent": "test_coverage", "status": status}]}})
        for name, status in [("failed", "failed"), ("completed", "success")]), encoding="utf-8")
    output = tmp_path / "result.jsonl"
    reviewer = SimpleNamespace(
        review=lambda *args, **kwargs: AgentReviewResult(agent="test_coverage", status="failed",
                                                         error_category="invalid_schema"),
        last_completion_metadata=CompletionMetadata(),
        last_validation_diagnostics=ValidationDiagnostics("missing_test_claim", 0),
    )
    args = ["--dataset", str(dataset), "--baseline", str(baseline), "--output", str(output),
            "--failed-only", "--confirm-paid-runs"]
    with patch.object(diagnostic.logging, "disable"), patch.object(diagnostic, "read_cases", return_value=cases), patch.object(
        diagnostic, "validate_reviewed_cases"
    ), patch.object(diagnostic, "load_fireworks_settings", return_value=SimpleNamespace(model="offline")), patch.object(
        diagnostic, "TestCoverageReviewer", return_value=reviewer
    ) as factory:
        assert diagnostic.main(args) == 0
        assert factory.call_count == 1
        with pytest.raises(FileExistsError):
            diagnostic.main(args)
        assert factory.call_count == 1
    row = json.loads(output.read_text())
    assert row["case_id"] == "failed" and row["result"]["status"] == "failed"
    assert row["validation"]["stage"] == "missing_test_claim"
    assert len(row["dataset_sha256"]) == len(row["reviewer_sha256"]) == 64
    assert json.loads(output.with_suffix(".summary.json").read_text())["successes"] == 0
