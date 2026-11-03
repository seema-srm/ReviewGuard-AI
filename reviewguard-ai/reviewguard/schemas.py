"""Shared review contracts and source-grounding checks; no agent or API calls."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
PositiveLine = Annotated[int, Field(strict=True, gt=0)]


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AgentType(str, Enum):
    code_quality = "code_quality"
    security = "security"
    test_coverage = "test_coverage"


class ReviewFinding(BaseModel):
    """One finding. Source-grounding requires validate_finding_against_source."""

    model_config = ConfigDict(extra="forbid")

    finding_id: NonEmptyText
    agent: AgentType
    title: NonEmptyText
    category: NonEmptyText
    severity: Severity
    filename: NonEmptyText
    line_number: PositiveLine | None = None
    end_line: PositiveLine | None = None
    description: NonEmptyText
    evidence: NonEmptyText
    recommendation: NonEmptyText
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    suggested_tests: list[NonEmptyText] | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> Self:
        if self.end_line is not None:
            if self.line_number is None:
                raise ValueError("end_line requires line_number")
            if self.end_line < self.line_number:
                raise ValueError("end_line must not precede line_number")
        return self


class AgentReviewResult(BaseModel):
    """Errors remain metadata, never synthetic findings."""

    model_config = ConfigDict(extra="forbid")

    agent: AgentType
    status: Literal["success", "failed", "skipped"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    error_message: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if any(finding.agent != self.agent for finding in self.findings):
            raise ValueError("Each finding's agent must match the result's agent")
        if self.status != "success" and self.findings:
            raise ValueError("Failed or skipped results must not contain findings")
        if self.status == "success" and self.error_message is not None:
            raise ValueError("Successful results must not contain an error_message")
        return self


class SourceValidationError(ValueError):
    """A finding references an unsupported file, line range, or evidence."""


def validate_finding_against_source(
    finding: ReviewFinding, source: str, *, filename: str
) -> ReviewFinding:
    """Return the finding or raise SourceValidationError; never invent findings.

    Filenames must match exactly. Lines are 1-based and inclusive, consistent
    with splitlines() in the upload utilities. A missing end_line selects only
    the start line; no line reference selects the whole file. Evidence must be
    a verbatim, contiguous substring in that selection, preserving whitespace
    and newline characters (including CRLF). No fuzzy matching or normalization
    is performed. This verifies grounding, not the finding's technical validity.
    """
    if finding.filename != filename:
        raise SourceValidationError("Finding filename does not match the supplied source filename")
    selected_source = source
    if finding.line_number is not None:
        lines = source.splitlines(keepends=True)
        end_line = finding.end_line or finding.line_number
        if finding.line_number > len(lines) or end_line > len(lines):
            raise SourceValidationError("Finding line reference is outside the supplied source")
        selected_source = "".join(lines[finding.line_number - 1 : end_line])
    if finding.evidence not in selected_source:
        raise SourceValidationError("Exact evidence was not found in the referenced source")
    return finding
