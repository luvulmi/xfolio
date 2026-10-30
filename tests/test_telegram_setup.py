import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "setup_telegram",
    Path(__file__).resolve().parents[1] / "scripts/dev/setup_telegram.py",
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
SetupError = setup.SetupError
api, save_chat, select_chat = setup.api, setup.save_chat, setup.select_chat


def message(chat_id=123, **changes):
    value = {
        "text": "/start xfolio_setup",
        "date": 1000,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": chat_id, "is_bot": False},
    }
    value.update(changes)
    return {"message": value}


def test_only_recent_private_setup_message_is_selected():
    assert select_chat([message(), message()], 1001) == "123"
    for invalid in (
        message(chat={"id": -123, "type": "group"}),
        message(date=0),
        message(text="/start"),
        message(**{"from": {"id": 456, "is_bot": False}}),
    ):
        with pytest.raises(SetupError, match="MISSING"):
            select_chat([invalid], 2000)
    with pytest.raises(SetupError, match="MULTIPLE"):
        select_chat([message(), message(456)], 1001)


def test_env_preserves_secrets_and_refuses_different_destination(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"OTHER_SECRET=keep\r\nTELEGRAM_CHAT_ID=\r\n")
    save_chat(path, "123")
    assert "OTHER_SECRET=keep" in path.read_text()
    assert "TELEGRAM_CHAT_ID=123" in path.read_text()
    before = path.read_bytes()
    with pytest.raises(SetupError, match="DIFFERS"):
        save_chat(path, "456")
    assert path.read_bytes() == before


def test_http_error_does_not_expose_token():
    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(SetupError) as exc,
    ):
        api(client, "123:secret", "getMe")
    assert str(exc.value) == "TELEGRAM_REQUEST_FAILED"
