"""예외 원문·locals·소스 줄·연결정보 없는 코드 위치 진단."""

import json
import sys
import warnings

import pytest

from xfolio.jobs.diagnostics import (
    emit_event,
    failure_details,
    safe_process_diagnostics,
)


def test_exception_details_do_not_include_messages_or_local_secrets(capsys):
    secret = "postgresql://private:password@example.invalid/db?token=private"
    try:
        raise RuntimeError(secret)
    except RuntimeError as exc:
        details = failure_details(exc, "market_collect")
    emit_event({"event": "preparation", "status": "failed", **details})
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["failed_stage"] == "market_collect"
    assert result["exception_type"] == "RuntimeError"
    assert result["frames"][-1]["file"] == "test_diagnostics.py"
    assert result["frames"][-1]["line"] > 0
    assert secret not in output and "password" not in output
    assert all(set(frame) == {"file", "function", "line"} for frame in result["frames"])


def test_stderr_warning_and_uncaught_exception_are_sanitized_and_hooks_restored(capsys):
    old_warning, old_hook = warnings.showwarning, sys.excepthook
    with warnings.catch_warnings(), safe_process_diagnostics():
        warnings.simplefilter("always")
        warnings.warn("private-token-in-warning", stacklevel=1)
        try:
            raise RuntimeError("private-database-url")
        except RuntimeError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)
    body = capsys.readouterr().err
    warning, error = [json.loads(line) for line in body.splitlines()]
    assert warning["category"] == "UserWarning"
    assert error["exception_type"] == "RuntimeError"
    assert "private" not in body
    assert warnings.showwarning is old_warning and sys.excepthook is old_hook


def test_uncaught_exception_exits_nonzero_without_raw_traceback(capsys):
    with pytest.raises(SystemExit) as exit_info, safe_process_diagnostics():
        raise RuntimeError("private-secret")
    assert exit_info.value.code == 1
    body = capsys.readouterr().err
    assert json.loads(body)["exception_type"] == "RuntimeError"
    assert "private-secret" not in body and "Traceback" not in body


def test_system_exit_message_is_not_written_to_stderr(capsys):
    with pytest.raises(SystemExit) as exit_info, safe_process_diagnostics():
        raise SystemExit("private-secret")
    assert exit_info.value.code == 1
    body = capsys.readouterr().err
    assert json.loads(body)["exception_type"] == "SystemExit"
    assert "private-secret" not in body
