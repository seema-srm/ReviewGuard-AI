"""Report envelope reusing the existing aggregation metadata."""

from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from reviewguard.orchestration.aggregation import AggregationResult
from reviewguard.schemas import Severity

ENGINEERING_WARNING = "Model findings require engineering verification."
CLEAN_REVIEW_WARNING = "A successful review does not prove code is free of bugs or vulnerabilities."


class ReviewReport(AggregationResult):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: UUID
    generated_at: datetime
    filename: str = Field(min_length=1)
    total_unique_findings: int = Field(ge=0)
    counts_by_severity: dict[Severity, int]
    warnings: tuple[str, ...] = (ENGINEERING_WARNING, CLEAN_REVIEW_WARNING)

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("Report timestamp must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        counts = {severity: 0 for severity in Severity}
        for group in self.findings:
            counts[group.representative.severity] += 1
        if self.total_unique_findings != len(self.findings) or self.counts_by_severity != counts:
            raise ValueError("Report counts do not match prioritized findings")
        if ENGINEERING_WARNING not in self.warnings or CLEAN_REVIEW_WARNING not in self.warnings:
            raise ValueError("Required review warnings are missing")
        # Even imported reports cannot transport arbitrary provider error bodies.
        safe_statuses = tuple(item.model_copy(update={"error_message": None if item.status == "success"
            else "Agent review failed; details suppressed." if item.status == "failed"
            else "Agent review skipped; details suppressed."}) for item in self.agent_statuses)
        object.__setattr__(self, "agent_statuses", safe_statuses)
        return self
