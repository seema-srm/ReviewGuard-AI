"""Langfuse settings and tracing stay offline unless explicitly enabled."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from openai import OpenAI

from reviewguard.fireworks_client import create_fireworks_request_client
from reviewguard.langfuse_client import (
    LangfuseConfigurationError,
    LangfuseSettings,
    create_langfuse_client,
    get_active_langfuse_client,
    load_langfuse_settings,
    use_langfuse_client,
)


def test_settings_are_disabled_by_default_even_with_credentials():
    with patch.dict("os.environ", {}, clear=True), patch(
        "reviewguard.langfuse_client.dotenv_values",
        return_value={
            "LANGFUSE_PUBLIC_KEY": "public-placeholder",
            "LANGFUSE_SECRET_KEY": "secret-placeholder",
        },
    ):
        assert load_langfuse_settings() is None


def test_enabled_settings_support_base_url_and_legacy_host_without_exposing_keys():
    with patch.dict(
        "os.environ",
        {
            "REVIEWGUARD_LANGFUSE_TRACING": "true",
            "LANGFUSE_PUBLIC_KEY": "public-placeholder",
            "LANGFUSE_SECRET_KEY": "secret-placeholder",
            "LANGFUSE_HOST": "https://us.cloud.langfuse.com/",
        },
        clear=True,
    ), patch("reviewguard.langfuse_client.dotenv_values", return_value={}):
        settings = load_langfuse_settings()

    assert settings == LangfuseSettings(
        "public-placeholder",
        "secret-placeholder",
        "https://us.cloud.langfuse.com",
    )
    assert "public-placeholder" not in repr(settings)
    assert "secret-placeholder" not in repr(settings)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://langfuse.example.com",
        "https://user:password@langfuse.example.com",
        "https://langfuse.example.com/?token=hidden",
        "https://langfuse.example.com:invalid",
    ],
)
def test_enabled_settings_reject_unsafe_base_urls_without_echoing_values(base_url):
    with patch.dict(
        "os.environ",
        {
            "LANGFUSE_PUBLIC_KEY": "public-placeholder",
            "LANGFUSE_SECRET_KEY": "secret-placeholder",
        },
        clear=True,
    ), patch(
        "reviewguard.langfuse_client.dotenv_values",
        return_value={"REVIEWGUARD_LANGFUSE_TRACING": "true", "LANGFUSE_BASE_URL": base_url},
    ):
        with pytest.raises(LangfuseConfigurationError) as error:
            load_langfuse_settings()

    assert base_url not in str(error.value)
    assert "secret-placeholder" not in str(error.value)


def test_enabled_settings_require_both_keys_without_disclosing_values():
    with patch.dict("os.environ", {}, clear=True), patch(
        "reviewguard.langfuse_client.dotenv_values",
        return_value={
            "REVIEWGUARD_LANGFUSE_TRACING": "true",
            "LANGFUSE_PUBLIC_KEY": "public-placeholder",
        },
    ):
        with pytest.raises(LangfuseConfigurationError) as error:
            load_langfuse_settings()

    assert "public-placeholder" not in str(error.value)


def test_client_creation_passes_explicit_configuration_without_connectivity_check():
    settings = LangfuseSettings("public-placeholder", "secret-placeholder")
    client = Mock()
    with patch("reviewguard.langfuse_client.Langfuse", return_value=client) as factory:
        assert create_langfuse_client(settings) is client

    factory.assert_called_once_with(
        public_key="public-placeholder",
        secret_key="secret-placeholder",
        base_url="https://cloud.langfuse.com",
        tracing_enabled=True,
    )


def test_request_client_records_generation_only_in_active_langfuse_context():
    openai_client = OpenAI(api_key="offline-placeholder")
    response = Mock()
    response.model_dump.return_value = {"id": "offline-response"}
    response.usage = Mock(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    original_create = Mock(return_value=response)
    openai_client.chat.completions.create = original_create
    observation = Mock()
    langfuse_client = Mock()
    calls = []

    @contextmanager
    def start_observation(**kwargs):
        calls.append(kwargs)
        yield observation

    langfuse_client.start_as_current_observation.side_effect = start_observation
    try:
        with use_langfuse_client(langfuse_client):
            with patch.object(openai_client, "with_options", return_value=openai_client), patch(
                "reviewguard.fireworks_client.wrap_openai",
                side_effect=lambda client, **_: client,
            ):
                request_client = create_fireworks_request_client(openai_client)
                result = request_client.chat.completions.create(
                    model="offline-model",
                    messages=[{"role": "user", "content": "offline source"}],
                )

        assert result is response
        assert calls == [
            {
                "as_type": "generation",
                "name": "ReviewGuard Fireworks",
                "model": "offline-model",
                "input": {"messages": [{"role": "user", "content": "offline source"}]},
            }
        ]
        observation.update.assert_called_once_with(
            output={"id": "offline-response"},
            usage_details={"input": 12, "output": 8, "total": 20},
        )
        assert get_active_langfuse_client() is None
    finally:
        openai_client.close()
