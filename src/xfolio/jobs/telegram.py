"""Telegram Bot API 연결. 비밀·HTTP 응답 본문을 오류로 전달하지 않는다."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

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


def validate_entities(text, entities):
    """Telegram의 UTF-16 위치를 확인한다. HTML/Markdown 구문 해석은 사용하지 않는다."""
    boundaries, units = {0}, 0
    for char in text:
        units += text_units(char)
        boundaries.add(units)
    for entity in entities:
        if not isinstance(entity, dict):
            raise TypeError("telegram_entity_invalid")
        offset, length = entity.get("offset"), entity.get("length")
        kind = entity.get("type")
        keys = {"type", "offset", "length"}
        if kind == "text_link":
            keys.add("url")
            url = entity.get("url")
            if not isinstance(url, str) or any(c.isspace() for c in url):
                raise ValueError("telegram_entity_url_invalid")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("telegram_entity_url_invalid")
        elif kind != "bold":
            raise ValueError("telegram_entity_type_invalid")
        if (
            set(entity) != keys
            or type(offset) is not int
            or type(length) is not int
            or length <= 0
            or offset not in boundaries
            or offset + length not in boundaries
        ):
            raise ValueError("telegram_entity_range_invalid")


def slice_entities(entities, offset, length):
    """분할 조각에 걸친 서식을 조각 시작 기준으로 옮긴다."""
    result = []
    for entity in entities:
        start = max(offset, entity["offset"])
        end = min(offset + length, entity["offset"] + entity["length"])
        if start < end:
            result.append(entity | {"offset": start - offset, "length": end - start})
    return tuple(result)


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
        self.entities = []

    def send(self, text, *, entities=()):
        validate_entities(text, entities)
        self.sent.append(text)
        self.entities.append(entities)
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

    def send(self, text, *, entities=()):
        if not text or text_units(text) > 4096:
            return SendResult("failed", error_code="telegram_text_invalid")
        try:
            validate_entities(text, entities)
        except (TypeError, ValueError):
            return SendResult("failed", error_code="telegram_entities_invalid")
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if entities:
            payload["entities"] = list(entities)
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json=payload,
            )
        except httpx.RequestError:
            return SendResult("unknown", error_code="telegram_result_unknown")
        return self._receipt(response)

    def send_document(self, *, filename, content, caption=""):
        """사용자가 요청한 소스 첨부. 수신자는 sendMessage와 동일한 본인 1:1이다."""
        if (
            not re.fullmatch(r"[a-zA-Z0-9_]+\.py", filename)
            or not isinstance(content, bytes)
            or not 0 < len(content) <= 1024 * 1024
            or text_units(caption) > 1024
        ):
            return SendResult("failed", error_code="telegram_document_invalid")
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{self._token}/sendDocument",
                data={"chat_id": self._chat_id, "caption": caption},
                files={"document": (filename, content, "text/x-python")},
            )
        except httpx.RequestError:
            return SendResult("unknown", error_code="telegram_result_unknown")
        return self._receipt(response)

    def _receipt(self, response):
        try:
            body = response.json()
        except ValueError:
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
