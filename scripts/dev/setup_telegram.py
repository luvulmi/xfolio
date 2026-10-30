"""Prepare a private Telegram destination without sending messages or logging secrets."""

import argparse
import logging
import os
import re
import time
from pathlib import Path

import httpx


class SetupError(Exception):
    pass


def api(client, token, method):
    try:
        response = client.post(f"https://api.telegram.org/bot{token}/{method}", json={})
        if response.status_code != 200:
            raise SetupError(f"TELEGRAM_HTTP_{response.status_code}")
        payload = response.json()
        if payload.get("ok") is not True:
            raise SetupError("TELEGRAM_API_FAILED")
        return payload["result"]
    except (httpx.HTTPError, ValueError, KeyError):
        raise SetupError("TELEGRAM_REQUEST_FAILED") from None


def select_chat(updates, now):
    candidates = set()
    for update in updates:
        message = update.get("message", {})
        chat = message.get("chat", {})
        sender = message.get("from", {})
        age = now - message.get("date", 0)
        if (
            message.get("text") == "/start xfolio_setup"
            and chat.get("type") == "private"
            and isinstance(chat.get("id"), int)
            and chat["id"] > 0
            and sender.get("id") == chat["id"]
            and sender.get("is_bot") is False
            and 0 <= age <= 1800
        ):
            candidates.add(str(chat["id"]))
    if len(candidates) != 1:
        raise SetupError(
            "SETUP_MESSAGE_MISSING_OR_OLD"
            if not candidates
            else "MULTIPLE_PRIVATE_CHATS"
        )
    return candidates.pop()


def save_chat(path, chat_id):
    original = path.read_bytes()
    text = original.decode("utf-8-sig")
    pattern = re.compile(
        r"^[ \t]*(?:export[ \t]+)?TELEGRAM_CHAT_ID[ \t]*=.*$", re.MULTILINE
    )
    matches = list(pattern.finditer(text))
    if len(matches) > 1:
        raise SetupError("DUPLICATE_CHAT_ID_SETTINGS")
    if matches:
        previous = matches[0].group().split("=", 1)[1].strip().strip("\"'")
        if previous and previous != chat_id:
            raise SetupError("EXISTING_CHAT_ID_DIFFERS")
        text = pattern.sub(f"TELEGRAM_CHAT_ID={chat_id}", text)
    else:
        text = text.rstrip("\r\n") + f"\nTELEGRAM_CHAT_ID={chat_id}\n"
    if path.read_bytes() != original:
        raise SetupError("ENV_CHANGED_RETRY")
    path.write_bytes(text.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--save-chat", action="store_true")
    args = parser.parse_args()
    if not args.run:
        print("DRY_RUN: getMe, getWebhookInfo, getUpdates; no messages sent.")
        return 0
    logging.disable(logging.CRITICAL)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        print("TOKEN_MISSING_OR_INVALID_FORMAT")
        return 1
    try:
        with httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            bot = api(client, token, "getMe")
            if bot.get("username") != "ringXFolioNotifyBot" or not bot.get("is_bot"):
                raise SetupError("BOT_USERNAME_MISMATCH")
            if api(client, token, "getWebhookInfo").get("url"):
                raise SetupError("WEBHOOK_ACTIVE_NO_CHANGES")
            # No offset: do not acknowledge/discard pending updates.
            chat_id = select_chat(api(client, token, "getUpdates"), time.time())
        if args.save_chat:
            save_chat(Path(__file__).resolve().parents[2] / ".env", chat_id)
        print(
            "BOT_VERIFIED: @ringXFolioNotifyBot; unique recent private setup message."
        )
        print("CHAT_ID_SAVED" if args.save_chat else "CHAT_ID_FOUND_NOT_SAVED")
        print("NO_MESSAGE_SENT")
        return 0
    except SetupError as exc:
        print(str(exc))
        return 1
    except Exception:  # noqa: BLE001 -- prevent secret-bearing exception output at CLI boundary
        # Never print provider responses, URLs containing tokens, or local .env data.
        print("SETUP_FAILED_NO_DETAILS_LOGGED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
