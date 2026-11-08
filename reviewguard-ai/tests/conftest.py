"""Offline helpers for dashboard regressions that explicitly click Review Code."""

from unittest.mock import patch

import pytest

from reviewguard.orchestration.aggregation import aggregate_findings
from reviewguard.reports.builder import build_review_report
from reviewguard.schemas import AgentReviewResult, AgentType


@pytest.fixture
def mock_ui_review():
    def completed(upload):
        aggregation = aggregate_findings({agent: AgentReviewResult(agent=agent, status="success", findings=[])
            for agent in AgentType}, sources={upload.filename: upload.source})
        return build_review_report(aggregation, filename=upload.filename)
    with patch("reviewguard.ui.review_service.run_review", side_effect=completed) as service:
        yield service
