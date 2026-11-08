"""Command-line workflow for candidate review, LangSmith upload and evaluation."""

import argparse
import os
from pathlib import Path
import sys

from langsmith import Client
from dotenv import load_dotenv

from reviewguard.evals.candidates import candidate_cases
from reviewguard.evals.runner import (
    evaluate_dataset,
    read_cases,
    require_live_evaluation_authorization,
    upload_dataset,
    validate_reviewed_cases,
)

DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[2] / "evals" / "candidate_dataset.jsonl"
APP_DIRECTORY = Path(__file__).resolve().parents[2]


def _write_candidates(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise ValueError(f"{path} already exists; use --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(case.model_dump_json() for case in candidate_cases()) + "\n"
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(candidate_cases())} candidate cases to {path}")
    print("All annotations are needs_review; this is not yet a golden dataset.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ReviewGuard evaluation workflow")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export-candidates", help="Write 30 unreviewed candidate cases")
    export.add_argument("--output", type=Path, default=DEFAULT_DATASET_PATH)
    export.add_argument("--force", action="store_true")

    validate = commands.add_parser("validate", help="Validate dataset schema and review status")
    validate.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)

    upload = commands.add_parser("upload", help="Upload fully reviewed cases to LangSmith")
    upload.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    upload.add_argument("--name", required=True)

    evaluate = commands.add_parser("evaluate", help="Run paid live evaluation on a LangSmith dataset")
    evaluate.add_argument("--name", required=True)
    evaluate.add_argument("--experiment-prefix", required=True)
    evaluate.add_argument("--confirm-paid-runs", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(APP_DIRECTORY / ".env", override=False)
    args = _parser().parse_args(argv)
    try:
        if args.command == "export-candidates":
            _write_candidates(args.output, args.force)
            return 0
        if args.command == "validate":
            cases = read_cases(args.dataset)
            reviewed = sum(case.annotation_status == "reviewed" for case in cases)
            print(f"Cases: {len(cases)}; reviewed: {reviewed}; pending review: {len(cases) - reviewed}")
            try:
                validate_reviewed_cases(cases)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print("Dataset is eligible for LangSmith upload and evaluation.")
            return 0
        if args.command == "upload":
            cases = read_cases(args.dataset)
            validate_reviewed_cases(cases)
            upload_dataset(Client(), args.name, cases)
            print(f"Uploaded {len(cases)} reviewed cases to LangSmith dataset {args.name!r}.")
            return 0
        if args.command == "evaluate":
            if not args.confirm_paid_runs:
                raise ValueError("Pass --confirm-paid-runs to confirm paid Fireworks requests")
            require_live_evaluation_authorization()
            results = evaluate_dataset(Client(), args.name, args.experiment_prefix)
            experiment_name = getattr(results, "experiment_name", args.experiment_prefix)
            project = os.getenv("LANGSMITH_PROJECT", "reviewguard")
            print(f"Experiment submitted: {experiment_name}")
            print(f"Inspect per-case results and traces in LangSmith project {project!r}.")
            return 0
    except Exception as exc:
        print(f"Evaluation command failed: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
