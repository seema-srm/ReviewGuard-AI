"""Validated local evaluation case format."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reviewguard.schemas import AgentType, Severity


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    severity: Severity


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    scenario_type: str = Field(min_length=1)
    annotation_status: Literal["needs_review", "reviewed"]
    reviewer: str | None = None
    reviewer_notes: str = ""
    target_agent: AgentType
    filename: str = Field(min_length=1)
    source: str
    existing_tests: dict[str, str] | None = None
    measured_coverage: dict[str, object] | None = None
    expected_findings: list[ExpectedFinding]

    @model_validator(mode="after")
    def require_review_metadata(self):
        if self.annotation_status == "reviewed" and not (self.reviewer or "").strip():
            raise ValueError("Reviewed cases require a reviewer name")
        if any(not item.anchor.strip() or item.anchor not in self.source for item in self.expected_findings):
            raise ValueError("Every expected finding anchor must occur verbatim in source")
        return self
