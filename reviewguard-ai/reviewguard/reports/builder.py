"""Pure report construction from already grounded aggregation data."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from reviewguard.orchestration.aggregation import AggregationResult
from reviewguard.reports.models import ReviewReport
from reviewguard.schemas import Severity


def build_review_report(
    aggregation: AggregationResult, *, filename: str,
    report_id: UUID | None = None, generated_at: datetime | None = None,
) -> ReviewReport:
    """Preserve aggregation ordering and originals; never accept or execute source.

    Optional identity/time values support deterministic verification. Consumers
    must supply aggregation produced by the source-validating aggregation stage.
    """
    checked = AggregationResult.model_validate(aggregation.model_dump())
    counts = {severity: 0 for severity in Severity}
    for group in checked.findings:
        counts[group.representative.severity] += 1
    return ReviewReport(
        **checked.model_dump(), filename=filename,
        report_id=report_id if report_id is not None else uuid4(),
        generated_at=generated_at if generated_at is not None else datetime.now(timezone.utc),
        total_unique_findings=len(checked.findings), counts_by_severity=counts,
    )
