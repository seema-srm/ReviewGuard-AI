"""Pure, conservative exact-identity deduplication and severity prioritization."""

from collections.abc import Mapping
import posixpath
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from reviewguard.schemas import AgentReviewResult, AgentType, ErrorCategory, normalize_error_category, ReviewFinding, Severity, validate_finding_against_source


class FindingProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent: AgentType
    finding_id: str


class AggregatedFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    representative: ReviewFinding
    provenance: tuple[FindingProvenance, ...]
    original_findings: tuple[ReviewFinding, ...]


class AgentExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent: AgentType
    status: Literal["success", "failed", "skipped"]
    error_message: str | None = None
    error_category: ErrorCategory | None = None

    @field_validator("error_category", mode="before")
    @classmethod
    def allowlisted_category(cls, value: object) -> ErrorCategory | None:
        return None if value is None else normalize_error_category(value)

    @model_validator(mode="after")
    def sanitize_error(self):
        object.__setattr__(self, "error_category", None if self.status == "success" else normalize_error_category(self.error_category))
        object.__setattr__(self, "error_message", None if self.status == "success" else
            "Agent review failed; details suppressed." if self.status == "failed" else "Agent review skipped; details suppressed.")
        return self


class AggregationResult(BaseModel):
    """Structured intermediate data, not a formatted final report."""

    model_config = ConfigDict(frozen=True)
    workflow_status: Literal["completed", "partial", "failed"]
    findings: tuple[AggregatedFinding, ...]
    agent_statuses: tuple[AgentExecution, ...]


def _text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _filename(value: str) -> str:
    # Lexical normalization only; never access the filesystem or casefold paths.
    return posixpath.normpath(value.replace("\\", "/"))


def _identity(finding: ReviewFinding) -> tuple:
    return (
        _filename(finding.filename), finding.line_number,
        finding.end_line if finding.end_line is not None else finding.line_number,
        _text(finding.category), _text(finding.title), _text(finding.description),
        # Without a line location, require exact evidence too.
        finding.evidence if finding.line_number is None else None,
    )


def _rank(finding: ReviewFinding) -> tuple:
    severity_order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
    return (
        severity_order[finding.severity], -finding.confidence,
        _filename(finding.filename), finding.line_number or float("inf"),
        finding.end_line or finding.line_number or float("inf"),
        _text(finding.category), _text(finding.title), _text(finding.description),
        finding.agent.value, finding.finding_id, finding.model_dump_json(),
    )


def aggregate_findings(
    agent_results: Mapping[AgentType, AgentReviewResult], *, sources: Mapping[str, str],
) -> AggregationResult:
    """Require all agent statuses, revalidate originals, and retain all variants.

    Exact normalized path/location/category/title/description define identity.
    No fuzzy matching, inference or line-overlap matching occurs. Original paths
    must exist exactly in sources for grounding before normalization is used.
    Evidence and recommendation variants never disappear: all originals remain
    in metadata, even when their identity matches. The highest-priority original
    is the representative; its severity/confidence are never modified or averaged.
    """
    if set(agent_results) != set(AgentType):
        raise ValueError("Aggregation requires explicit results from all three agents")
    statuses = []
    groups: dict[tuple, list[ReviewFinding]] = {}
    for agent in sorted(AgentType, key=lambda item: item.value):
        result = AgentReviewResult.model_validate(agent_results[agent].model_dump())
        if result.agent != agent:
            raise ValueError("Agent result key mismatch")
        statuses.append(AgentExecution(agent=agent, status=result.status, error_category=result.error_category,
            error_message=None if result.status == "success" else "Agent review failed; details suppressed."
            if result.status == "failed" else "Agent review skipped; details suppressed."))
        if result.status != "success":
            continue
        for finding in result.findings:
            if finding.filename not in sources:
                raise ValueError("Source unavailable for finding validation")
            validate_finding_against_source(finding, sources[finding.filename], filename=finding.filename)
            groups.setdefault(_identity(finding), []).append(finding.model_copy(deep=True))
    findings = []
    for originals in groups.values():
        originals.sort(key=_rank)
        findings.append(AggregatedFinding(
            representative=originals[0].model_copy(deep=True),
            provenance=tuple(FindingProvenance(agent=item.agent, finding_id=item.finding_id) for item in originals),
            original_findings=tuple(originals),
        ))
    findings.sort(key=lambda group: _rank(group.representative))
    successes = sum(item.status == "success" for item in statuses)
    return AggregationResult(
        workflow_status="completed" if successes == 3 else "partial" if successes else "failed",
        findings=tuple(findings), agent_statuses=tuple(statuses),
    )
