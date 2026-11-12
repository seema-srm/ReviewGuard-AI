from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from reviewguard.evals.candidates import candidate_cases
from reviewguard.evals import cli
from reviewguard.evals.runner import read_cases, validate_reviewed_cases
from reviewguard.evals.scoring import langsmith_evaluator, score_review


def finding(agent="security", severity="HIGH", evidence="cursor.execute(query)"):
    return {
        "agent": agent,
        "severity": severity,
        "evidence": evidence,
    }


def report(findings, *, workflow="completed", target_status="success"):
    return {
        "workflow_status": workflow,
        "agent_statuses": [{"agent": "security", "status": target_status}],
        "findings": [
            {"original_findings": [item], "representative": item}
            for item in findings
        ],
    }


def test_candidate_set_has_30_unreviewed_cases_split_across_all_agents():
    cases = candidate_cases()
    assert len(cases) == 30
    assert {case.target_agent.value for case in cases} == {
        "code_quality", "security", "test_coverage",
    }
    assert all(case.annotation_status == "needs_review" for case in cases)


def test_cli_loads_application_env_without_overriding_process_environment(tmp_path, monkeypatch):
    observed = {}

    def fake_load_dotenv(path, *, override):
        observed["path"] = path
        observed["override"] = override

    monkeypatch.setattr(cli, "APP_DIRECTORY", tmp_path)
    with patch.object(cli, "load_dotenv", side_effect=fake_load_dotenv), \
         patch.object(cli, "read_cases", return_value=candidate_cases()):
        status = cli.main(["validate"])

    assert status == 2
    assert observed == {"path": tmp_path / ".env", "override": False}


def test_reviewed_dataset_requires_complete_human_adjudication(tmp_path):
    cases = candidate_cases()
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(case.model_dump_json() for case in cases), encoding="utf-8")
    loaded = read_cases(path)
    with pytest.raises(ValueError, match="still need human review"):
        validate_reviewed_cases(loaded)
    with pytest.raises(ValueError, match="must contain 30-50 cases"):
        validate_reviewed_cases([case for case in loaded if case.annotation_status == "reviewed"])


def test_scoring_reports_precision_recall_f1_and_severity_separately():
    expected = {
        "expected_findings": [
            {"label": "sql_injection", "anchor": "cursor.execute(query)", "severity": "HIGH"},
            {"label": "unsafe_eval", "anchor": "eval(expression)", "severity": "HIGH"},
        ],
    }
    actual = report([
        finding(evidence="cursor.execute(query)"),
        finding(evidence="return eval(expression)"),
        finding(evidence="open(untrusted_path)"),
    ])
    scores = score_review(actual, expected, target_agent="security")
    assert scores == {
        "finding_precision": pytest.approx(2 / 3),
        "finding_recall": 1.0,
        "finding_f1": pytest.approx(0.8),
        "exact_match": 0.0,
        "severity_accuracy": 1.0,
    }


def test_scoring_does_not_count_other_agents_as_target_predictions():
    actual = report([finding(agent="code_quality")])
    scores = score_review(actual, {"expected_findings": []}, target_agent="security")
    assert scores["finding_precision"] == 1
    assert scores["finding_recall"] == 1
    assert scores["exact_match"] == 1


@pytest.mark.parametrize("actual", [None, report([], target_status="failed"),
                                    report([], target_status="skipped")])
def test_failed_negative_case_does_not_receive_perfect_quality_scores(actual):
    scores = score_review(actual, {"expected_findings": []}, target_agent="security")
    assert all(value == 0 for value in scores.values())


def test_langsmith_evaluator_includes_completion_and_observed_latency():
    start = datetime(2026, 1, 1)
    run = SimpleNamespace(
        outputs={"report": report([finding()])},
        start_time=start,
        end_time=start.replace(second=2),
        prompt_tokens=12,
        completion_tokens=8,
        total_tokens=20,
        total_cost=0.01,
    )
    example = SimpleNamespace(
        inputs={"target_agent": "security"},
        outputs={"expected_findings": [
            {"anchor": "cursor.execute(query)", "severity": "HIGH"},
        ]},
    )
    results = {
        item["key"]: item.get("score", item.get("value"))
        for item in langsmith_evaluator(run, example)
    }
    assert results["finding_f1"] == 1
    assert results["workflow_completion"] == 1
    assert results["target_agent_success"] == 1
    assert results["latency_ms"] == 2000
    assert results["total_tokens"] == 20
    assert results["cost_usd"] == 0.01
    assert results["failure_category"] == "none"
