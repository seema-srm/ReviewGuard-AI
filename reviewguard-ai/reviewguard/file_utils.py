"""Validate source files in memory without executing or saving them."""

from dataclasses import dataclass
from pathlib import PurePath

from reviewguard.config import MAX_FILE_SIZE_BYTES


class FileValidationError(ValueError):
    """An upload does not meet the supported file requirements."""


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    size_bytes: int
    source: str
    line_count: int


def count_lines(source: str) -> int:
    """Count logical text lines; a final newline adds no extra line."""
    return len(source.splitlines())


def validate_python_file(filename: str, content: bytes) -> ValidatedFile:
    """Accept a .py file up to 1 MiB, including an empty UTF-8 file."""
    if PurePath(filename).suffix.lower() != ".py":
        raise FileValidationError("Unsupported file extension. Upload a .py file.")
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileValidationError("File exceeds the 1 MB (1,048,576 bytes) limit.")
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileValidationError("Invalid UTF-8 encoding. Save the file as UTF-8 and retry.") from exc
    return ValidatedFile(filename, len(content), source, count_lines(source))
