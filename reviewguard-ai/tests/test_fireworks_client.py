from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from reviewguard.fireworks_client import (
    ConfigurationError,
    FIREWORKS_ENDPOINT,
    FireworksSettings,
    create_fireworks_client,
    load_fireworks_settings,
)
from scripts.test_fireworks_connection import response_text, sanitized_error, validate_status_json
from scripts import test_fireworks_connection as diagnostic


def test_configuration_uses_application_directory(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    values = {"FIREWORKS_API_KEY": "fake-secret", "FIREWORKS_MODEL": "test-model"}
    with patch.dict("os.environ", {}, clear=True), patch("reviewguard.fireworks_client.dotenv_values", return_value=values) as read:
        settings = load_fireworks_settings()
    assert settings.model == "test-model"
    assert "fake-secret" not in repr(settings)
    assert read.call_args.args[0].name == ".env"
    assert read.call_args.args[0].parent.name == "reviewguard-ai"


def test_client_has_no_retries_and_bounded_timeout() -> None:
    with patch("reviewguard.fireworks_client.OpenAI") as client:
        create_fireworks_client(FireworksSettings("fake-secret", "test-model"))
    assert client.call_args.kwargs["max_retries"] == 0
    assert client.call_args.kwargs["timeout"] == 30.0
    assert client.call_args.kwargs["base_url"] == FIREWORKS_ENDPOINT


@pytest.mark.parametrize("values", [{}, {"FIREWORKS_API_KEY": "fake-secret", "FIREWORKS_MODEL": "m", "FIREWORKS_BASE_URL": "https://example.com"}])
def test_bad_configuration_is_safe(values: dict) -> None:
    with patch.dict("os.environ", {}, clear=True), patch("reviewguard.fireworks_client.dotenv_values", return_value=values):
        with pytest.raises(ConfigurationError) as error:
            load_fireworks_settings()
    assert "fake-secret" not in str(error.value)


@pytest.mark.parametrize("text, valid", [('{"status":"ok"}', True), ('{"status":"bad"}', False), ('{"status":"ok","extra":1}', False), ("not JSON", False), ("[]", False)])
def test_json_validation(text: str, valid: bool) -> None:
    assert validate_status_json(text) is valid


def test_response_rejects_truncation_and_empty_output() -> None:
    for reason, content in [("length", "partial"), ("stop", " "), ("stop", None)]:
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason, message=SimpleNamespace(content=content))])
        with pytest.raises(ValueError):
            response_text(response)


def test_unknown_error_does_not_echo_secret() -> None:
    assert "fake-secret" not in sanitized_error(RuntimeError("fake-secret"))


def test_diagnostic_makes_two_calls_without_retry_and_redacts(capsys) -> None:
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="fake-secret"))])
    client.chat.completions.create.side_effect = [RuntimeError("fake-secret"), response]
    with patch.object(diagnostic, "load_fireworks_settings", return_value=FireworksSettings("fake-secret", "model")), patch.object(diagnostic, "create_fireworks_client", return_value=client), patch.object(diagnostic.logging, "disable"):
        assert diagnostic.main() == 1
    assert client.chat.completions.create.call_count == 2
    calls = client.chat.completions.create.call_args_list
    assert calls[0].kwargs["messages"][0]["content"] == "Reply with exactly: CONNECTION_OK"
    assert calls[1].kwargs["response_format"] == {"type": "json_object"}
    assert "fake-secret" not in capsys.readouterr().out
