"""Local baselines must persist failures and never silently repeat paid runs."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from reviewguard.evals import local
from reviewguard.evals.models import EvaluationCase


def test_missing_paid_flag_never_loads_configuration():
    with patch.object(local, "load_fireworks_settings") as settings, pytest.raises(SystemExit):
        local.main(["--dataset", "unused", "--output", "unused"])
    settings.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_local_baseline_persists_results_and_refuses_overwrite(tmp_path, fails):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("offline dataset", encoding="utf-8")
    output = tmp_path / "results.jsonl"
    case = EvaluationCase(case_id="negative", scenario_type="safe", annotation_status="reviewed",
                          reviewer="test", reviewer_notes="offline fixture", target_agent="security",
                          filename="safe.py", source="pass\n", expected_findings=[])
    report = Mock()
    report.model_dump.return_value = {
        "workflow_status": "completed", "findings": [],
        "agent_statuses": [{"agent": "security", "status": "success"}],
    }
    args = ["--dataset", str(dataset), "--output", str(output), "--confirm-paid-runs"]
    with patch.object(local.logging, "disable"), patch.object(local, "read_cases", return_value=[case]), patch.object(
        local, "validate_reviewed_cases"
    ), patch.object(local, "load_fireworks_settings", return_value=SimpleNamespace(model="offline-model")), patch.object(
        local, "run_review", return_value=report,
        side_effect=RuntimeError("private provider body") if fails else None,
    ) as review:
        assert local.main(args) == 0
        assert review.call_count == 1
        with pytest.raises(FileExistsError):
            local.main(args)
        assert review.call_count == 1
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["scores"]["exact_match"] == (0 if fails else 1)
    assert row["target_status"] == ("failed" if fails else "success")
    assert "private provider body" not in output.read_text(encoding="utf-8")
    assert output.with_suffix(".summary.json").exists()
