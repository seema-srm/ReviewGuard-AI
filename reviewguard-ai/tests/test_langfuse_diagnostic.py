"""Offline checks for explicit authorization and safe diagnostic output."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scripts import test_langfuse_connection as diagnostic


def test_no_confirmation_sends_no_requests(capsys):
    with patch.object(diagnostic, "load_fireworks_settings") as settings:
        assert diagnostic.main([]) == 2
    settings.assert_not_called()
    assert "No calls sent" in capsys.readouterr().out


@pytest.mark.parametrize("auth_ok", [False, True])
def test_authentication_precedes_inference_and_verifies_persisted_generations(auth_ok, capsys):
    client = Mock()
    client.auth_check.return_value = auth_ok
    client.create_trace_id.return_value = "offline-trace"
    client.api.observations.get_many.return_value.data = [
        SimpleNamespace(type="GENERATION", input={}, output={}, usage_details={"total": 10})
        for _ in range(3)
    ]
    report = SimpleNamespace(workflow_status="completed", agent_statuses=[])
    with patch.object(diagnostic.logging, "disable"), patch.object(
        diagnostic, "load_fireworks_settings"
    ), patch.object(diagnostic, "load_langfuse_settings"), patch.object(
        diagnostic, "create_langfuse_client", return_value=client
    ), patch.object(diagnostic, "run_review", return_value=report) as review:
        assert diagnostic.main(["--confirm-paid-run"]) == (0 if auth_ok else 1)
    assert review.call_count == int(auth_ok)
    client.shutdown.assert_called_once()
    if auth_ok:
        assert review.call_args.kwargs["tracing_enabled"] is False
        assert review.call_args.kwargs["langfuse_tracing_enabled"] is True
        assert "Persisted generations: 3/3" in capsys.readouterr().out


def test_remote_exception_is_sanitized_and_never_retried(capsys):
    client = Mock()
    client.auth_check.side_effect = RuntimeError("sensitive-provider-body")
    with patch.object(diagnostic.logging, "disable"), patch.object(
        diagnostic, "load_fireworks_settings"
    ), patch.object(diagnostic, "load_langfuse_settings"), patch.object(
        diagnostic, "create_langfuse_client", return_value=client
    ), patch.object(diagnostic, "run_review") as review:
        assert diagnostic.main(["--confirm-paid-run"]) == 1
    review.assert_not_called()
    client.auth_check.assert_called_once()
    assert "sensitive-provider-body" not in capsys.readouterr().out
