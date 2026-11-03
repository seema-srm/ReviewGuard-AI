from pathlib import Path
from unittest.mock import patch
from io import BytesIO
import ast

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class MemoryUpload(BytesIO):
    def __init__(self, name: str, data: bytes) -> None:
        super().__init__(data)
        self.name = name
        self.size = len(data)


def test_app_startup() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert app.title[0].value == "ReviewGuard AI"
    assert app.button[0].disabled


def test_upload_preview_and_review_button() -> None:
    with patch("streamlit.file_uploader", return_value=MemoryUpload("sample.py", b"x = 1\n")):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not app.exception
        # Streamlit strips trailing whitespace when rendering code blocks.
        assert app.code[0].value == "x = 1"
        app.button[0].click().run()
        assert not app.exception
        assert app.info[0].value == "AI review agents will be available in Phase 2."


@pytest.mark.parametrize("name, data, error", [("bad.txt", b"pass", "extension"), ("bad.py", b"\xff", "UTF-8"), ("large.py", b" " * (1024 * 1024 + 1), "limit")])
def test_invalid_upload_shows_error(name: str, data: bytes, error: str) -> None:
    with patch("streamlit.file_uploader", return_value=MemoryUpload(name, data)):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not app.exception
        assert error in app.error[0].value
        assert not app.code


@pytest.mark.parametrize("filename", ["clean_example.py", "buggy_example.py"])
def test_sample_upload_metadata_and_source(filename: str) -> None:
    data = (APP_PATH.parent / "samples" / filename).read_bytes()
    source = data.decode("utf-8")
    with patch("streamlit.file_uploader", return_value=MemoryUpload(filename, data)):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not app.exception
        assert not app.error
        displayed = [element.value for element in app.markdown]
        assert f"Filename: {filename}" in displayed
        assert f"File size: {len(data):,} bytes" in displayed
        assert f"Line count: {len(source.splitlines())}" in displayed
        assert app.code[0].value == source.strip()
        assert app.code[0].proto.language == "python"
        app.button[0].click().run()
        assert not app.exception
        assert app.info[0].value == "AI review agents will be available in Phase 2."


def test_empty_upload_ui() -> None:
    with patch("streamlit.file_uploader", return_value=MemoryUpload("empty.py", b"")):
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not app.exception
        assert not app.error
        assert app.info[0].value == "This file is empty (0 lines)."
        assert app.code[0].value == ""
        displayed = [element.value for element in app.markdown]
        assert "File size: 0 bytes" in displayed
        assert "Line count: 0" in displayed


def test_uploaded_source_is_not_executed_or_saved(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed.txt"
    source = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "raise RuntimeError('Uploaded code was executed')\n"
    )
    # A valid Python program with observable side effects must remain plain text.
    with patch("streamlit.file_uploader", return_value=MemoryUpload("sentinel.py", source.encode())):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.button[0].click().run()
        assert not app.exception
        assert app.code[0].value == source.strip()
        assert not sentinel.exists()
        assert not list(tmp_path.iterdir())


def test_application_has_no_execution_or_disk_write_calls() -> None:
    # Structural regression check alongside the dynamic sentinel test.
    forbidden = {
        "exec", "eval", "compile", "open", "write", "write_text", "write_bytes",
        "save", "dump", "dumps", "system", "popen", "Popen", "run", "call",
        "check_call", "check_output", "NamedTemporaryFile", "TemporaryFile",
    }
    paths = [APP_PATH, *sorted((APP_PATH.parent / "reviewguard").glob("*.py"))]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden, str(path)
            elif isinstance(node.func, ast.Attribute):
                # st.write renders text in the UI; it is not a file write.
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "st":
                    continue
                assert node.func.attr not in forbidden, str(path)
