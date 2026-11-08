"""Headless dashboard layout and placeholder safety checks."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"
pytestmark = pytest.mark.usefixtures("mock_ui_review")


class Upload(BytesIO):
    def __init__(self, name: str, content: bytes):
        super().__init__(content)
        self.name = name
        self.size = len(content)


def test_dashboard_sections_and_empty_results():
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.title[0].value == "ReviewGuard AI"
    assert "Multi-Agent Code Review Platform" in [item.value for item in app.markdown]
    assert [item.value for item in app.header] == ["Source code", "Review configuration", "Review results"]
    headings = [item.value for item in app.subheader]
    for label in ("Code Quality Reviewer", "Security Reviewer", "Test Coverage Reviewer",
                  "Review summary", "Severity counts", "Agent execution statuses", "Prioritized findings", "JSON report export"):
        assert label in headings
    assert [item.label for item in app.metric] == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    assert all(item.value == "—" for item in app.metric)
    assert app.button[0].disabled
    assert "No review has been run" in app.info[0].value
    assert app.get("download_button")[0].proto.disabled
    assert not app.code


def test_review_is_placeholder_and_makes_no_network_or_graph_calls():
    with patch("streamlit.file_uploader", return_value=Upload("example.py", b"pass\n")), \
         patch("reviewguard.orchestration.graph.build_review_graph", side_effect=AssertionError("Graph prohibited")) as graph, \
         patch("httpx.Client.send", side_effect=AssertionError("Network prohibited")) as transport:
        app = AppTest.from_file(str(APP)).run()
        assert not app.exception and app.code[0].value == "pass"
        app.button[0].click().run()
        assert not app.exception
        assert app.success[0].value == "Review status: completed"
        assert "zero accepted findings" in app.info[0].value
        assert app.session_state.review_report is not None
        assert not app.get("download_button")[0].proto.disabled
    graph.assert_not_called()
    transport.assert_not_called()


@pytest.mark.parametrize("name,data,expected", [("bad.txt", b"pass", "extension"),
    ("bad.py", b"\xff", "UTF-8"), ("large.py", b" " * (1048576 + 1), "limit")])
def test_invalid_upload_keeps_results_empty_and_review_disabled(name, data, expected):
    with patch("streamlit.file_uploader", return_value=Upload(name, data)):
        app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert expected in app.error[0].value
    assert app.button[0].disabled and not app.code
    assert "No review has been run" in app.info[0].value
    assert all(item.value == "—" for item in app.metric)


def test_removing_upload_clears_preview_and_placeholder_message():
    with patch("streamlit.file_uploader", return_value=Upload("example.py", b"x = 1\n")):
        app = AppTest.from_file(str(APP)).run()
        app.button[0].click().run()
        assert not app.exception and app.code
    with patch("streamlit.file_uploader", return_value=None):
        app.run()
    assert not app.exception and not app.code
    assert app.button[0].disabled
    assert all("AI review agents" not in item.value for item in app.info)
