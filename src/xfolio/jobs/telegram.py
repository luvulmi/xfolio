"""Telegram plain text 경계. 비밀·HTTP 응답 본문을 오류로 전달하지 않는다."""

import re
from dataclasses import dataclass

import httpx


def text_units(text):
    return len(text.encode("utf-16-le")) // 2


def split_text(text, *, limit=4000):
    """보수적인 UTF-16 단위 상한. 연결하면 원본과 정확히 같으며 parse_mode 없음."""
    if not isinstance(text, str) or not text or not 1 <= limit <= 4096:
        raise ValueError("telegram_text_invalid")
    parts, current, units = [], [], 0
    for char in text:
        count = text_units(char)
        if count > limit:
            raise ValueError("telegram_limit_too_small")
        if units + count > limit:
            parts.append("".join(current))
            current, units = [], 0
        current.append(char)
        units += count
    if current:
        parts.append("".join(current))
    return tuple(parts)


@dataclass(frozen=True)
class SendResult:
    status: str
    message_id: str | None = None
    error_code: str | None = None
    retry_after: int | None = None


class MockTelegramTransport:
    mode = "mock"

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return SendResult("confirmed", message_id=f"mock-{len(self.sent)}")


class TelegramTransport:
    mode = "live"

    def __init__(self, *, token, chat_id, client=None):
        if not re.fullmatch(r"[0-9]+:[a-zA-Z0-9_-]+", token or ""):
            raise ValueError("telegram_token_invalid")
        if not re.fullmatch(r"[1-9][0-9]*", str(chat_id)):
            raise ValueError("telegram_private_recipient_required")
        self._token, self._chat_id = token, str(chat_id)
        self.client = client or httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        )
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()

    def send(self, text):
        if not text or text_units(text) > 4096:
            return SendResult("failed", error_code="telegram_text_invalid")
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "link_preview_options": {"is_disabled": True},
                },
            )
            body = response.json()
        except (httpx.RequestError, ValueError):
            return SendResult("unknown", error_code="telegram_result_unknown")
        if not isinstance(body, dict):
            return SendResult("unknown", error_code="telegram_response_invalid")
        if response.status_code == 429 and body.get("ok") is False:
            params = body.get("parameters")
            delay = params.get("retry_after") if isinstance(params, dict) else None
            if type(delay) is int and 1 <= delay <= 3600:
                return SendResult(
                    "retryable_failure",
                    error_code="telegram_rate_limited",
                    retry_after=delay,
                )
            return SendResult("failed", error_code="telegram_retry_after_invalid")
        if response.status_code == 200 and body.get("ok") is True:
            result = body.get("result")
            if (
                isinstance(result, dict)
                and type(result.get("message_id")) is int
                and result["message_id"] > 0
                and isinstance(result.get("chat"), dict)
                and str(result["chat"].get("id")) == self._chat_id
                and result["chat"].get("type") == "private"
            ):
                return SendResult("confirmed", message_id=str(result["message_id"]))
            return SendResult("unknown", error_code="telegram_receipt_unverified")
        if 400 <= response.status_code < 500 and body.get("ok") is False:
            return SendResult("failed", error_code="telegram_request_rejected")
        return SendResult("unknown", error_code="telegram_result_unknown")
