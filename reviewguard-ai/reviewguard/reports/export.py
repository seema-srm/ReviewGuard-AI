"""Guarded Pydantic JSON serialization; no network calls or file writes."""

from collections.abc import Iterable
import os
from pathlib import Path
import re

from dotenv import dotenv_values

from reviewguard.reports.models import ReviewReport


class UnsafeReportError(ValueError):
    """Export refused; error text never includes the detected content."""


def export_report_json(report: ReviewReport, *, sensitive_values: Iterable[str] = ()) -> str:
    """Fail closed on configured secrets/patterns, without altering exact evidence.

    Checks application .env and runtime secret variables silently, plus optional
    caller-supplied values and common token/private-key/credential patterns.
    This is a conservative safeguard, not a universal secret detector.
    """
    checked = ReviewReport.model_validate(report.model_dump())
    configured = dotenv_values(Path(__file__).resolve().parents[2] / ".env", interpolate=False)
    values = [*configured.items(), *os.environ.items()]
    secrets = [value for name, value in values if value and len(value) >= 8
               and any(marker in name.upper() for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL"))]
    secrets.extend(value for value in sensitive_values if isinstance(value, str) and value)
    # Inspect decoded field values as well as serialized output so JSON escaping
    # cannot conceal a credential containing quotes or newline characters.
    payload = checked.model_dump(mode="json")

    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from strings(key)
                yield from strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from strings(item)

    pattern = re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        r"\bAKIA[0-9A-Z]{16}\b|(?:ghp_|ghs_|github_pat_)[A-Za-z0-9_]{30,}|"
        r"\b(?:sk-|fw_)[A-Za-z0-9_-]{24,}|"
        r"(?i:(?:api[_-]?key|password|secret|access[_-]?token)\s*[=:]\s*['\"][^'\"]{8,}['\"])"
    )
    for text in strings(payload):
        if any(secret in text for secret in secrets) or pattern.search(text):
            raise UnsafeReportError("Report export blocked: potentially sensitive content detected.")
    return checked.model_dump_json(indent=2)
