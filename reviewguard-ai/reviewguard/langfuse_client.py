"""Opt-in Langfuse configuration and request-scoped client context."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator
from urllib.parse import urlsplit

from dotenv import dotenv_values
from langfuse import Langfuse

APP_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_LANGFUSE_BASE_URL = "https://cloud.langfuse.com"


class LangfuseConfigurationError(ValueError):
    """Missing or invalid Langfuse configuration without credential values."""


@dataclass(frozen=True)
class LangfuseSettings:
    public_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    base_url: str = DEFAULT_LANGFUSE_BASE_URL


_active_client: ContextVar[Langfuse | None] = ContextVar(
    "reviewguard_langfuse_client", default=None
)


def _tracing_is_enabled(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"", "0", "false", "no"}:
        return False
    raise LangfuseConfigurationError(
        "REVIEWGUARD_LANGFUSE_TRACING must be true or false."
    )


def _validate_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise LangfuseConfigurationError(
            "LANGFUSE_BASE_URL must be an HTTPS URL (HTTP is allowed for localhost)."
        ) from None
    local_http = parsed.scheme == "http" and hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (parsed.scheme != "https" and not local_http)
    ):
        raise LangfuseConfigurationError(
            "LANGFUSE_BASE_URL must be an HTTPS URL (HTTP is allowed for localhost)."
        )
    return base_url


def load_langfuse_settings(
    tracing_enabled: bool | None = None,
) -> LangfuseSettings | None:
    """Read opt-in settings from the app .env; process environment takes precedence."""
    values = {
        **dotenv_values(APP_DIRECTORY / ".env", interpolate=False),
        **os.environ,
    }
    if tracing_enabled is None:
        tracing_enabled = _tracing_is_enabled(
            values.get("REVIEWGUARD_LANGFUSE_TRACING")
        )
    if not tracing_enabled:
        return None

    public_key = (values.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (values.get("LANGFUSE_SECRET_KEY") or "").strip()
    if not public_key or not secret_key:
        raise LangfuseConfigurationError(
            "Langfuse tracing requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
        )

    base_url = (
        values.get("LANGFUSE_BASE_URL")
        or values.get("LANGFUSE_HOST")
        or DEFAULT_LANGFUSE_BASE_URL
    )
    return LangfuseSettings(
        public_key=public_key,
        secret_key=secret_key,
        base_url=_validate_base_url(base_url),
    )


def create_langfuse_client(settings: LangfuseSettings) -> Langfuse:
    """Create an explicitly enabled client without performing a connectivity check."""
    return Langfuse(
        public_key=settings.public_key,
        secret_key=settings.secret_key,
        base_url=settings.base_url,
        tracing_enabled=True,
    )


@contextmanager
def use_langfuse_client(client: Langfuse) -> Generator[None, None, None]:
    token = _active_client.set(client)
    try:
        yield
    finally:
        _active_client.reset(token)


def get_active_langfuse_client() -> Langfuse | None:
    """Return the client active in this request, including copied worker contexts."""
    return _active_client.get()
