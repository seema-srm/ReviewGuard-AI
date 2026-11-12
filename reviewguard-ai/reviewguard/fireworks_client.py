"""Explicit, reusable Fireworks configuration and client creation.

Importing this module does not read credentials or make network requests.
"""

import os
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

from dotenv import dotenv_values
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from reviewguard.langfuse_client import get_active_langfuse_client

APP_DIRECTORY = Path(__file__).resolve().parents[1]
FIREWORKS_ENDPOINT = "https://api.fireworks.ai/inference/v1"


class ConfigurationError(ValueError):
    """Missing or invalid Fireworks configuration (message contains no values)."""


@dataclass(frozen=True)
class FireworksSettings:
    api_key: str = field(repr=False)
    model: str
    base_url: str = FIREWORKS_ENDPOINT


def load_fireworks_settings() -> FireworksSettings:
    """Read the application .env explicitly; process environment takes precedence."""
    values = {
        **dotenv_values(APP_DIRECTORY / ".env", interpolate=False),
        **os.environ,
    }
    key = (values.get("FIREWORKS_API_KEY") or "").strip()
    model = (values.get("FIREWORKS_MODEL") or "").strip()
    base_url = (values.get("FIREWORKS_BASE_URL") or FIREWORKS_ENDPOINT).strip().rstrip("/")
    if not key or not model:
        raise ConfigurationError("FIREWORKS_API_KEY and FIREWORKS_MODEL must be configured.")
    # Prevent credentials being sent to a typo, Markdown link, or arbitrary host.
    if base_url != FIREWORKS_ENDPOINT:
        raise ConfigurationError("FIREWORKS_BASE_URL must be the plain Fireworks HTTPS inference URL.")
    return FireworksSettings(key, model, base_url)


def create_fireworks_client(settings: FireworksSettings) -> OpenAI:
    """Create a 30-second client with automatic paid-request retries disabled."""
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=30.0,
        max_retries=0,
    )


def create_fireworks_request_client(client: OpenAI) -> OpenAI:
    """Apply bounded request options, then instrument the actual request client."""
    request_client = client.with_options(timeout=30.0, max_retries=0)
    if isinstance(request_client, OpenAI):
        langfuse_client = get_active_langfuse_client()
        if langfuse_client is not None:
            create_completion = request_client.chat.completions.create

            @wraps(create_completion)
            def trace_completion(*args, **kwargs):
                with langfuse_client.start_as_current_observation(
                    as_type="generation",
                    name="ReviewGuard Fireworks",
                    model=kwargs.get("model"),
                    input={"messages": kwargs.get("messages")},
                ) as observation:
                    response = create_completion(*args, **kwargs)
                    usage = getattr(response, "usage", None)
                    usage_details = {}
                    for field_name, label in (
                        ("prompt_tokens", "input"),
                        ("completion_tokens", "output"),
                        ("total_tokens", "total"),
                    ):
                        count = getattr(usage, field_name, None)
                        if type(count) is int and count >= 0:
                            usage_details[label] = count
                    observation.update(
                        output=response.model_dump(mode="json"),
                        usage_details=usage_details or None,
                    )
                    return response

            request_client.chat.completions.create = trace_completion
        return wrap_openai(request_client, chat_name="ReviewGuard Fireworks")
    return request_client
