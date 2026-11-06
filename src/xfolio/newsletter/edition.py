"""T04 국내 종가+뉴스 아침 편성 및 전송 직전 검사. I/O와 송신은 별도다."""

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from xfolio.ai.title_translation import TranslatedTitle
from xfolio.domestic.calendar import KST, completed_sessions
from xfolio.domestic.models import (
    Collection,
    Contract,
    DomesticError,
    Instrument,
    Session,
)
from xfolio.news.collection import NewsResult, aware
from xfolio.news.contracts import digest
from xfolio.newsletter.presentation import PriceRow, StoryRow, render_morning


class NewsletterError(ValueError):
    """비밀·제공처 응답을 포함하지 않는 고정 오류 코드."""


def fingerprint(value):
    return digest(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), KST)


class AcceptanceSchedule(Contract):
    """서버에서 명시 주입하는 사용자 승인 단발 시험. 기본 운영 시각과 독립."""

    target_date: date
    recipient_scope: str = Field(pattern=r"^self_acceptance_[a-zA-Z0-9_]+$")
    frozen_at: AwareDatetime
    send_at: AwareDatetime
    deadline: AwareDatetime

    @model_validator(mode="after")
    def valid_times(self):
        if not self.frozen_at < self.send_at < self.deadline:
            raise ValueError("acceptance_times_invalid")
        if any(
            t.astimezone(KST).date() != self.target_date
            for t in (self.frozen_at, self.send_at, self.deadline)
        ):
            raise ValueError("acceptance_date_invalid")
        return self


def schedule_times(day, scope, schedule=None):
    if schedule is None:
        return at(day, 7, 50), at(day, 8), at(day, 8, 10)
    if schedule.target_date != day or schedule.recipient_scope != scope:
        raise NewsletterError("acceptance_scope_or_date_mismatch")
    return schedule.frozen_at, schedule.send_at, schedule.deadline


def stamp(value):
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def one_line(value):
    return " ".join(value.split())


class MorningSettings(Contract):
    revision: int = Field(ge=1)
    morning_enabled: bool = True
    paused: bool = False
    intraday_enabled: bool = False
    close_enabled: bool = False


class MorningInputs(Contract):
    target_date: date
    recipient_scope: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    frozen_at: AwareDatetime
    settings: MorningSettings
    watchlist_revision: int = Field(ge=1)
    instruments: tuple[Instrument, ...] = Field(min_length=1, max_length=10)
    market_run_id: str = Field(min_length=1)
    market: Collection
    calendar_opened: dict[date, bool]
    session_overrides: dict[date, Session] = Field(default_factory=dict)
    news: NewsResult
    mode: Literal["dry_run", "live"] = "dry_run"
    synthetic: bool = True

    @model_validator(mode="after")
    def instruments_unique(self):
        if len(set(self.codes)) != len(self.codes):
            raise ValueError("duplicate_instrument")
        return self

    @property
    def codes(self):
        return tuple(i.code for i in self.instruments)

    @property
    def input_hash(self):
        # 원문 근거는 해시 계산에도 영속 payload에도 복제하지 않는다.
        value = self.model_dump(mode="json", exclude={"news"})
        value["news"] = self.news.report()
        return fingerprint(value)


class MorningEdition(Contract):
    schema_version: Literal["morning_newsletter_v1"] = "morning_newsletter_v1"
    slot: Literal["morning"] = "morning"
    target_date: date
    recipient_scope: str
    created_at: AwareDatetime
    frozen_at: AwareDatetime
    settings: MorningSettings
    watchlist_revision: int
    codes: tuple[str, ...]
    market_run_id: str
    news_run_id: str
    input_hash: str
    mode: Literal["dry_run", "live"]
    synthetic: bool
    status: Literal["ready", "partial", "failed", "skipped"]
    market_open: bool | None
    reasons: tuple[str, ...]
    price_count: int = Field(ge=0, le=10)
    news_count: int = Field(ge=0, le=3)
    news_state: Literal["complete", "partial", "failed"]
    news_item_ids: tuple[str, ...]
    news_keys: tuple[str, ...]
    price_snapshot_ids: tuple[str, ...] = ()
    expires_at: AwareDatetime
    body: str
    entities: tuple[dict, ...] = ()
    title_translations: tuple[TranslatedTitle, ...] = ()
    title_translation_requested: bool = False

    @property
    def key(self):
        return fingerprint(
            [self.recipient_scope, self.target_date.isoformat(), self.slot]
        )


def build_morning(
    inputs: MorningInputs,
    *,
    now,
    corrected_codes=(),
    source_expires_at=None,
    schedule=None,
    title_translations=None,
):
    """검사 제외 사유를 남기고 정상 자료를 보존한다. ready는 실제 전송 허가가 아니다."""
    inputs = MorningInputs.model_validate_json(inputs.model_dump_json())
    now = aware(now)
    cutoff, send_at, deadline = schedule_times(
        inputs.target_date, inputs.recipient_scope, schedule
    )
    reasons, fatal = [], []
    market, news = inputs.market, inputs.news
    if inputs.target_date.weekday() >= 5:
        fatal.append("weekend")
    if inputs.frozen_at != cutoff or not cutoff <= now < deadline:
        fatal.append("preparation_time_invalid")
    if (
        market.requested_codes != inputs.codes
        or market.watchlist_revision != inputs.watchlist_revision
    ):
        fatal.append("watchlist_snapshot_mismatch")
    if not cutoff <= market.started_at <= market.finished_at <= now:
        fatal.append("market_collection_time_invalid")
    if news.as_of != cutoff or not cutoff <= news.finished_at <= now:
        fatal.append("news_collection_time_invalid")
    if any(
        not i.eligible or i.retrieved_at > inputs.frozen_at for i in inputs.instruments
    ):
        fatal.append("instrument_unverified")
    try:
        sessions = completed_sessions(
            cutoff, inputs.calendar_opened, overrides=inputs.session_overrides
        )
    except DomesticError:
        sessions = None
        fatal.append("calendar_unverified")
    market_open = inputs.calendar_opened.get(inputs.target_date) if sessions else None
    skipped = inputs.target_date.weekday() >= 5 or market_open is False
    if market_open is False:
        fatal.append("market_closed")

    quotes = {q.code: q for q in market.quotes}
    accepted_prices, price_rows = [], []
    expiries = [now + timedelta(days=90)]
    for instrument in inputs.instruments:
        code, q = instrument.code, quotes.get(instrument.code)
        valid = q is not None and sessions is not None and not fatal
        if valid:
            valid = (
                q.previous.trade_date == sessions[0].trade_date
                and q.latest.trade_date == sessions[1].trade_date
                and q.previous.scheduled_close == sessions[0].scheduled_close
                and q.latest.scheduled_close == sessions[1].scheduled_close
                and market.started_at <= q.retrieved_at <= market.finished_at
            )
        if not valid:
            reason = market.errors.get(code, "price_session_or_time_invalid")
            reasons.append(f"price_unavailable:{code}:{reason}")
            price_rows.append(PriceRow(instrument.name, None))
            continue
        accepted_prices.append(q)
        price_rows.append(PriceRow(instrument.name, q, code in corrected_codes))
        expiries.append(q.retrieved_at + timedelta(days=90))
        change = None if code in corrected_codes else q.change_pct
        if change is None:
            reasons.append(f"price_change_unverified:{code}")
    if not accepted_prices:
        reasons.append("all_prices_unavailable")

    selected, seen = [], set()
    source_items = {(s.provider, i.source_id): i for s in news.sources for i in s.items}
    failed_sources = {s.provider for s in news.sources if s.status == "failed"}
    for item in news.selected:
        original = source_items.get((item.provider, item.source_id))
        permitted = (
            original is not None
            and item.provider not in failed_sources
            and news.status != "failed"
            and original.model_dump(exclude={"summary_ko", "importance"})
            == item.model_dump(exclude={"summary_ko", "importance"})
            and item.retrieved_at >= cutoff
            and not seen.intersection(item.keys)
            and not fatal
        )
        if item.kind == "link":
            permitted = (
                permitted
                and item.permission_reference == "finnhub_personal_use:2026-11-03"
            )
        else:
            pattern = " ".join(
                "(?:" + "|".join(re.escape(t) for t in f.allowed_texts) + ")"
                for f in item.facts
            )
            permitted = permitted and bool(
                item.summary_ko and re.fullmatch(pattern, item.summary_ko)
            )
        if not permitted:
            reasons.append(
                "news_candidate_unverified:"
                + item.provider
                + ":"
                + digest(item.source_id)[:12]
            )
            continue
        seen.update(item.keys)
        selected.append(item)
        expiries.append(item.retrieved_at + timedelta(days=90))

    if news.status == "failed":
        reasons.append("news_collection_failed")
    elif news.status == "partial":
        reasons.append("news_collection_partial")
    for source in news.sources:
        if source.status != "complete":
            reasons.append("news_source_" + source.status + ":" + source.provider)
    if source_expires_at is not None:
        expiries.append(aware(source_expires_at))
    if min(expiries) <= now:
        fatal.append("source_expired")
    if not accepted_prices and not selected:
        fatal.append("no_usable_content")
    translations = tuple(
        TranslatedTitle.model_validate(t) for t in (title_translations or ())
    )
    translation_map = {
        (t.source_id, t.content_version, t.title): t for t in translations
    }
    candidate_titles = {
        (i.source_id, i.content_version, i.title) for i in news.selected
    }
    if (
        len(translation_map) != len(translations)
        or not set(translation_map) <= candidate_titles
    ):
        raise NewsletterError("title_translation_source_mismatch")
    expected_titles = {(i.source_id, i.content_version, i.title) for i in selected}
    translations = tuple(
        t
        for t in translations
        if (t.source_id, t.content_version, t.title) in expected_titles
    )
    if title_translations is not None and expected_titles - set(translation_map):
        reasons.append("title_translation_unavailable")
    rendered = render_morning(
        day=inputs.target_date,
        send_at=send_at,
        frozen_at=cutoff,
        prices=price_rows,
        stories=[
            StoryRow(
                i.title,
                i.publisher,
                i.published_at,
                i.kind,
                i.url,
                i.summary_ko,
                title_ko=translation_map[
                    (i.source_id, i.content_version, i.title)
                ].title_ko
                if (i.source_id, i.content_version, i.title) in translation_map
                else None,
                translation_requested=title_translations is not None,
            )
            for i in selected
        ],
        news_status=news.status,
        normal_zero=news.normal_zero,
        synthetic=inputs.synthetic or any(i.synthetic for i in selected),
        preview=inputs.mode == "dry_run",
        acceptance=schedule is not None,
    )
    body, entities = rendered.text, rendered.entities
    if fatal:
        lines = [
            f"XFolio 아침 뉴스레터 · {inputs.target_date.isoformat()}",
            "휴장일 정상 건너뜀 · 발송 없음"
            if skipped
            else "편성 실패: 발송을 보류합니다.",
        ]
        body, entities = "\n".join(lines), ()
    from xfolio.news.collection_store import item_id

    return MorningEdition(
        target_date=inputs.target_date,
        recipient_scope=inputs.recipient_scope,
        created_at=now,
        frozen_at=aware(inputs.frozen_at),
        settings=inputs.settings,
        watchlist_revision=inputs.watchlist_revision,
        codes=inputs.codes,
        market_run_id=inputs.market_run_id,
        news_run_id=news.run_id,
        input_hash=inputs.input_hash,
        mode=inputs.mode,
        synthetic=inputs.synthetic or any(i.synthetic for i in selected),
        status="skipped"
        if skipped
        else "failed"
        if fatal
        else "partial"
        if reasons
        else "ready",
        market_open=market_open,
        reasons=tuple(dict.fromkeys([*fatal, *reasons])),
        price_count=len(accepted_prices),
        news_count=len(selected),
        news_state=news.status,
        news_item_ids=tuple(item_id(i) for i in selected),
        news_keys=tuple(sorted(seen)),
        expires_at=aware(min(expiries)),
        body=body,
        entities=entities,
        title_translations=translations,
        title_translation_requested=title_translations is not None,
    )


class BudgetState(Contract):
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    checked_at: AwareDatetime
    limit_krw: Decimal = Field(
        default=Decimal(50000), gt=0, le=50000, allow_inf_nan=False
    )
    confirmed_krw: Decimal = Field(ge=0, allow_inf_nan=False)
    reserved_krw: Decimal = Field(ge=0, allow_inf_nan=False)
    expected_krw: Decimal = Field(ge=0, allow_inf_nan=False)


class SendContext(Contract):
    now: AwareDatetime
    settings: MorningSettings
    watchlist_revision: int = Field(ge=1)
    active_codes: tuple[str, ...]
    recipient_scope: str
    allowed_recipient_scopes: tuple[str, ...]
    chat_type: Literal["private", "group", "supergroup", "channel"]
    market_open: bool | None
    calendar_checked_at: AwareDatetime
    budget: BudgetState
    delivery_state: Literal[
        "not_started",
        "retryable_failure",
        "sending",
        "confirmed",
        "partial",
        "failed",
        "unknown",
    ] = "not_started"


class SendDecision(Contract):
    can_send: bool
    reasons: tuple[str, ...]


def check_send(edition: MorningEdition, context: SendContext, *, schedule=None):
    """호출자는 전송 직전 DB/서버 설정을 읽어야 한다. 점유·송신은 T06에서 수행."""
    edition = MorningEdition.model_validate_json(edition.model_dump_json())
    context = SendContext.model_validate_json(context.model_dump_json())
    now, reasons = aware(context.now), []
    cutoff, send_at, deadline = schedule_times(
        edition.target_date, edition.recipient_scope, schedule
    )
    if edition.status not in {"ready", "partial"} or not (
        edition.price_count or edition.news_count
    ):
        reasons.append("edition_not_prepared")
    if (
        edition.market_open is not True
        or context.market_open is not True
        or not edition.frozen_at <= context.calendar_checked_at <= now
    ):
        reasons.append("market_closed_or_unverified")
    if edition.mode != "live" or edition.synthetic:
        reasons.append("dry_run_or_synthetic")
    if edition.target_date.weekday() >= 5:
        reasons.append("weekend")
    if not send_at <= now < deadline:
        reasons.append("outside_send_window")
    if edition.created_at > now or edition.expires_at <= now:
        reasons.append("edition_expired_or_future")
    if edition.frozen_at != cutoff:
        reasons.append("freeze_invalid")
    if not context.settings.morning_enabled or context.settings.paused:
        reasons.append("disabled_or_paused")
    if context.settings != edition.settings:
        reasons.append("settings_changed")
    if (
        context.watchlist_revision != edition.watchlist_revision
        or context.active_codes != edition.codes
    ):
        reasons.append("watchlist_changed")
    if (
        context.allowed_recipient_scopes != (edition.recipient_scope,)
        or context.recipient_scope != edition.recipient_scope
        or context.chat_type != "private"
    ):
        reasons.append("recipient_not_allowed")
    budget = context.budget
    if (
        budget.month != now.astimezone(KST).strftime("%Y-%m")
        or not edition.created_at <= budget.checked_at <= now
    ):
        reasons.append("budget_not_current")
    if (
        budget.confirmed_krw + budget.reserved_krw + budget.expected_krw
        > budget.limit_krw
    ):
        reasons.append("monthly_budget_exceeded")
    if context.delivery_state not in {"not_started", "retryable_failure"}:
        reasons.append("delivery_already_started_or_unsafe")
    return SendDecision(can_send=not reasons, reasons=tuple(reasons))
