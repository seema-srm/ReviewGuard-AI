import pytest

from reviewguard.config import MAX_FILE_SIZE_BYTES
from reviewguard.file_utils import FileValidationError, count_lines, validate_python_file


def test_valid_python_file() -> None:
    result = validate_python_file("example.py", b"x = 1\n")
    assert result.filename == "example.py"
    assert result.source == "x = 1\n"
    assert result.size_bytes == 6
    assert result.line_count == 1


@pytest.mark.parametrize("filename", ["code.txt", "code.py.exe", "code", ""])
def test_invalid_extension(filename: str) -> None:
    with pytest.raises(FileValidationError, match="extension"):
        validate_python_file(filename, b"pass")


def test_size_limit() -> None:
    assert validate_python_file("limit.py", b" " * MAX_FILE_SIZE_BYTES).size_bytes == MAX_FILE_SIZE_BYTES
    with pytest.raises(FileValidationError, match="limit"):
        validate_python_file("large.py", b" " * (MAX_FILE_SIZE_BYTES + 1))


def test_invalid_utf8() -> None:
    with pytest.raises(FileValidationError, match="UTF-8"):
        validate_python_file("code.py", b"\xff\xfe")


def test_empty_file() -> None:
    result = validate_python_file("empty.py", b"")
    assert (result.source, result.size_bytes, result.line_count) == ("", 0, 0)


@pytest.mark.parametrize("source, expected", [("", 0), ("pass", 1), ("pass\n", 1), ("a\nb", 2), ("a\r\nb\r\n", 2), ("\n\n", 2)])
def test_line_count(source: str, expected: int) -> None:
    assert count_lines(source) == expected


def test_unicode_source() -> None:
    assert validate_python_file("CODE.PY", "# café\n".encode("utf-8")).source == "# café\n"
