"""Opt-in live diagnostic: at most two paid requests, never automatic retries.

Run with the virtual environment's Python. Pytest does not run these live calls.
"""

import json
import logging
from pathlib import Path
import sys

# Permit direct execution from any terminal working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import APIConnectionError, APIStatusError, APITimeoutError

from reviewguard.fireworks_client import (
    ConfigurationError,
    create_fireworks_client,
    load_fireworks_settings,
)


def sanitized_error(exc: Exception) -> str:
    """Use allowlisted diagnostics; never print remote error bodies or exception text."""
    if isinstance(exc, ConfigurationError):
        return "ConfigurationError: check required variables and the plain Fireworks HTTPS URL."
    if isinstance(exc, APITimeoutError):
        return "APITimeoutError: request timed out; server processing may still have occurred."
    if isinstance(exc, APIConnectionError):
        return "APIConnectionError: check network access, DNS, TLS, and firewall settings."
    if isinstance(exc, APIStatusError):
        causes = {
            400: "request parameters or response format may be unsupported",
            401: "API key is invalid or expired",
            402: "account credit or billing issue",
            403: "account lacks model access or permission",
            404: "configured model or endpoint is unavailable",
            422: "request parameters or response format failed validation",
            429: "rate limit or account quota exceeded",
        }
        status = exc.status_code
        cause = causes.get(status, "provider service error" if status >= 500 else "request rejected")
        return f"APIStatusError (HTTP {status}): {cause}."
    return "LocalOrResponseError: invalid response or local SDK/configuration failure."


def response_text(response: object) -> str:
    """Reject empty, truncated, or non-text completions."""
    choices = getattr(response, "choices", [])
    if not choices or choices[0].finish_reason != "stop":
        raise ValueError("No completed output")
    text = choices[0].message.content
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty output")
    return text.strip()


def validate_status_json(text: str) -> bool:
    """Require the exact small object, not just syntactically valid JSON."""
    try:
        return json.loads(text) == {"status": "ok"}
    except (ValueError, TypeError):
        return False


def main() -> int:
    # SDK debug configuration must not expose headers, requests, or credentials.
    logging.disable(logging.CRITICAL)
    try:
        settings = load_fireworks_settings()
        client = create_fireworks_client(settings)
    except Exception as exc:
        print(sanitized_error(exc))
        print("Connection: NOT VERIFIED; JSON compatibility: NOT VERIFIED; no calls sent.")
        return 1

    successful = True
    with client:
        for json_mode in (False, True):
            label = "JSON mode" if json_mode else "Connection"
            try:
                options = {"response_format": {"type": "json_object"}} if json_mode else {}
                prompt = 'Reply with only the JSON object {"status": "ok"}.' if json_mode else "Reply with exactly: CONNECTION_OK"
                response = client.chat.completions.create(
                    model=settings.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                    **options,
                )
                text = response_text(response)
                # Escape control characters and redact the key even if a server echoes it.
                safe_text = text.replace(settings.api_key, "[REDACTED]")
                print(f"{label} returned: {json.dumps(safe_text, ensure_ascii=True)}")
                valid = validate_status_json(text) if json_mode else text == "CONNECTION_OK"
                print(f"{label}: {'PASS' if valid else 'FAIL (unexpected output)'}")
                successful = successful and valid
            except Exception as exc:
                successful = False
                print(f"{label}: FAIL; {sanitized_error(exc)}")
                if json_mode:
                    print("JSON compatibility: NOT VERIFIED; request failed, unsupported format not established.")
            # Each mode is attempted once; errors never cause a retry or model switch.
    if not successful:
        print('If JSON mode is unsupported, use prompt-only JSON plus json.loads and exact schema validation; reject invalid output without automatic retries.')
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
