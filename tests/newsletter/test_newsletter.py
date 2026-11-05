"""T04 편성/발송 검사: 외부 API·AI·DB·Telegram 없이 정책 경계를 검증."""

import json
import socket
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from xfolio.cli import main
from xfolio.domestic.models import Collection
from xfolio.news.collection import NewsResult, SourceResult, integrate
from xfolio.newsletter.demo import demo_inputs
from xfolio.newsletter.edition import (
    BudgetState,
    MorningInputs,
    MorningSettings,
    SendContext,
    at,
    build_morning,
    check_send,
)

DAY = date(2026, 11, 4)
PREPARED = at(DAY, 7, 58)
SEND = at(DAY, 8)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def inputs(*, scenario="news", live=False, **changes):
    value = demo_inputs(scenario).model_dump()
    if live:
        news = value["news"]
        for item in news["selected"]:
            item["synthetic"] = False
        for source in news["sources"]:
            for item in source["items"]:
                item["synthetic"] = False
        value.update(mode="live", synthetic=False)
    return MorningInputs.model_validate(value | changes)


def context(**changes):
    value = {
        "now": SEND,
        "settings": MorningSettings(revision=1),
        "watchlist_revision": 1,
        "active_codes": inputs().codes,
        "recipient_scope": "self",
        "allowed_recipient_scopes": ("self",),
        "chat_type": "private",
        "market_open": True,
        "calendar_checked_at": SEND,
        "budget": BudgetState(
            month="2026-11",
            checked_at=SEND,
            confirmed_krw=10000,
            reserved_krw=20000,
            expected_krw=20000,
        ),
    }
    return SendContext.model_validate(value | changes)


def edition(**kw):
    return build_morning(inputs(live=True, **kw), now=PREPARED)


def test_price_and_general_official_total_three_plain_text_and_provenance():
    result = edition()
    assert result.status == "ready" and (result.price_count, result.news_count) == (
        3,
        3,
    )
    assert result.slot == "morning" and result.codes == ("360750", "379810", "458730")
    assert (
        "기준 거래일 2026-11-03" in result.body
        and "비교 거래일 2026-11-02" in result.body
    )
    assert "25,100원 / +0.40%" in result.body
    assert (
        "가격 기준시각: 미제공" in result.body
        and "조회 2026-11-04 07:51" in result.body
    )
    assert "달력 예정 마감" in result.body and "지연 여부 미확인" in result.body
    assert result.body.count("AI 요약:") == 1 and result.body.count("https://") == 3
    assert "Synthetic US stocks earnings report 1" in result.body
    assert "출처 CNBC · 발행" in result.body and "2.5%" in result.body
    assert result.frozen_at.utcoffset() == result.created_at.utcoffset() == timedelta(0)
    assert not result.settings.intraday_enabled and not result.settings.close_enabled
    assert check_send(result, context()).can_send
    payload = result.model_dump_json()
    assert '"facts"' not in payload and "evidence_span" not in payload


def test_normal_zero_partial_and_both_failures_are_distinct():
    zero = edition(scenario="zero")
    assert (
        zero.status == "ready"
        and zero.news_count == 0
        and "적격 뉴스 없음" in zero.body
    )
    partial = edition(scenario="partial")
    assert partial.status == "partial" and partial.price_count == 2
    assert "종가 확인 불가" in partial.body and "뉴스 수집 일부 실패" in partial.body
    assert check_send(partial, context()).can_send
    failed = edition(scenario="failed")
    assert failed.status == "failed" and "no_usable_content" in failed.reasons
    assert not check_send(failed, context()).can_send


def test_news_failed_with_good_prices_still_prepared_and_price_failure_with_news():
    data = inputs(live=True)
    sources = tuple(
        SourceResult(provider=p, status="failed", errors=("http_503",), requests=1)
        for p in ("Finnhub", "BLS", "BEA", "Board")
    )
    failed_news = integrate(
        sources, as_of=data.frozen_at, finished_at=PREPARED, run_id="failed-news"
    )
    result = build_morning(inputs(live=True, news=failed_news), now=PREPARED)
    assert (
        result.status == "partial"
        and result.price_count == 3
        and result.news_count == 0
    )
    assert "뉴스 수집 실패" in result.body and "적격 뉴스 없음" not in result.body
    assert check_send(result, context()).can_send
    market = Collection.model_validate(
        data.market.model_dump()
        | {"quotes": (), "errors": {c: "provider_unavailable" for c in data.codes}}
    )
    result = build_morning(inputs(live=True, market=market), now=PREPARED)
    assert (
        result.status == "partial" and result.news_count == 3 and not result.price_count
    )
    assert "가격 데이터 장애" in result.body and check_send(result, context()).can_send


@pytest.mark.parametrize("day", [date(2026, 11, 7), date(2026, 11, 8)])
def test_weekend_is_skipped(day):
    data = demo_inputs(target_date=day)
    result = build_morning(data, now=at(day, 7, 58))
    assert result.status == "skipped" and "weekend" in result.reasons
    assert result.body.count("https://") == 0


@pytest.mark.parametrize("day", [date(2026, 11, 9), date(2026, 12, 25)])
def test_monday_or_korean_weekday_holiday_uses_last_completed_session(day):
    data = demo_inputs(target_date=day)
    result = build_morning(data, now=at(day, 7, 58))
    assert data.market.quotes[0].latest.trade_date < day
    if day.month == 12:
        assert result.status == "skipped" and "정상 건너뜀" in result.body
        assert result.market_open is False
    else:
        assert result.status == "ready"
        assert "2026-11-06" in result.body


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"frozen_at": at(DAY, 7, 49)}, "preparation_time_invalid"),
        ({"watchlist_revision": 2}, "watchlist_snapshot_mismatch"),
        (
            {"instruments": tuple(reversed(demo_inputs().instruments))},
            "watchlist_snapshot_mismatch",
        ),
    ],
)
def test_freeze_and_versions_block(change, reason):
    result = edition(**change)
    assert result.status == "failed" and reason in result.reasons


@pytest.mark.parametrize("now", [at(DAY, 7, 49), at(DAY, 8, 10), at(DAY, 8, 11)])
def test_invalid_preparation_time(now):
    result = build_morning(inputs(), now=now)
    assert result.status == "failed" and "preparation_time_invalid" in result.reasons


def test_0758_is_target_not_hard_deadline():
    assert build_morning(inputs(), now=at(DAY, 8, 2)).status == "ready"


def test_missing_or_disagreeing_calendar_blocks_all_sending():
    for calendar in [{}, demo_inputs().calendar_opened | {DAY: False}]:
        result = edition(calendar_opened=calendar)
        assert (
            result.status == "failed"
            and result.price_count == 0
            and result.news_count == 0
        )
        assert "calendar_unverified" in result.reasons


def test_wrong_price_dates_cannot_substitute_for_expected_session():
    data = demo_inputs(target_date=date(2026, 11, 3))
    market = data.market.model_copy(
        update={
            "started_at": at(DAY, 7, 50),
            "finished_at": at(DAY, 7, 52),
            "quotes": tuple(
                q.model_copy(update={"retrieved_at": at(DAY, 7, 51)})
                for q in data.market.quotes
            ),
        }
    )
    result = edition(market=market)
    assert (
        result.status == "partial"
        and result.price_count == 0
        and result.news_count == 3
    )


@pytest.mark.parametrize("review", ["split", "distribution"])
def test_split_or_distribution_and_corrected_price_behavior(review):
    data = inputs(live=True)
    quotes = tuple(
        q.model_copy(
            update={
                "event_review": review,
                "event_evidence": "https://example.invalid/action",
            }
        )
        for q in data.market.quotes
    )
    market = data.market.model_copy(update={"quotes": quotes})
    result = edition(market=market)
    assert result.price_count == 3
    if review == "split":
        assert result.status == "partial" and "등락률 확인 불가" in result.body
    else:
        assert "분배락" in result.body and "분배금을 포함하지 않은" in result.body
    corrected = build_morning(data, now=PREPARED, corrected_codes=(data.codes[0],))
    assert corrected.status == "partial" and "정정 가격" in corrected.body


@pytest.mark.parametrize(
    "kind", ["permission", "summary", "unlinked", "late_cutoff", "synthetic"]
)
def test_news_rechecked_instead_of_trusting_selected_flag(kind):
    data = inputs(live=True)
    news = data.news.model_dump()
    selected = news["selected"]
    if kind == "permission":
        selected[1]["permission_reference"] = "unverified"
    elif kind == "summary":
        selected[0]["summary_ko"] = "GDP 99% 증가, 투자하세요."
    elif kind == "unlinked":
        for source in news["sources"]:
            source["items"] = ()
    elif kind == "late_cutoff":
        news["as_of"] = at(DAY, 7, 51)
    else:
        selected[1]["synthetic"] = True
        for source in news["sources"]:
            for item in source["items"]:
                if item["source_id"] == selected[1]["source_id"]:
                    item["synthetic"] = True
    result = edition(news=NewsResult.model_validate(news))
    if kind == "synthetic":
        assert result.synthetic and not check_send(result, context()).can_send
    elif kind == "late_cutoff":
        assert result.status == "failed"
    else:
        assert result.status == "partial" and result.news_count < 3
        assert "99%" not in result.body and "unverified" not in result.body


def test_old_news_is_labelled_and_future_publication_and_fourth_news_rejected():
    data = inputs()
    news = data.news.model_dump()
    for item in news["selected"]:
        item["published_at"] = data.frozen_at - timedelta(hours=48)
    for source in news["sources"]:
        for item in source["items"]:
            item["published_at"] = data.frozen_at - timedelta(hours=48)
    result = edition(news=NewsResult.model_validate(news))
    assert "24시간 이전 발행 보완" in result.body
    with pytest.raises(ValidationError):
        NewsResult.model_validate(
            data.news.model_dump()
            | {"selected": data.news.selected + (data.news.selected[0],)}
        )
    with pytest.raises(ValidationError):
        NewsResult.model_validate(
            data.news.model_dump() | {"as_of": data.frozen_at - timedelta(days=5)}
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"now": at(DAY, 7, 59)}, "outside_send_window"),
        ({"now": at(DAY, 8, 10)}, "outside_send_window"),
        ({"now": at(DAY + timedelta(days=1), 8)}, "outside_send_window"),
        ({"settings": MorningSettings(revision=2)}, "settings_changed"),
        ({"settings": MorningSettings(revision=2, paused=True)}, "disabled_or_paused"),
        (
            {"settings": MorningSettings(revision=1, morning_enabled=False)},
            "disabled_or_paused",
        ),
        ({"watchlist_revision": 2}, "watchlist_changed"),
        ({"active_codes": ("360750",)}, "watchlist_changed"),
        ({"recipient_scope": "other"}, "recipient_not_allowed"),
        ({"allowed_recipient_scopes": ("self", "other")}, "recipient_not_allowed"),
        ({"chat_type": "group"}, "recipient_not_allowed"),
        ({"market_open": False}, "market_closed_or_unverified"),
        ({"market_open": None}, "market_closed_or_unverified"),
        (
            {"calendar_checked_at": SEND + timedelta(seconds=1)},
            "market_closed_or_unverified",
        ),
    ],
)
def test_send_context_guards(change, reason):
    result = check_send(edition(), context(**change))
    assert not result.can_send and reason in result.reasons


@pytest.mark.parametrize(
    "state", ["sending", "confirmed", "partial", "failed", "unknown"]
)
def test_send_never_retries_unsafe_or_started_transmission(state):
    assert not check_send(edition(), context(delivery_state=state)).can_send


def test_safe_failure_retry_only_inside_deadline_and_budget_exact_boundary():
    assert check_send(edition(), context(delivery_state="retryable_failure")).can_send
    budget = context().budget
    assert check_send(edition(), context()).can_send
    for change, reason in [
        ({"expected_krw": Decimal("20000.01")}, "monthly_budget_exceeded"),
        ({"month": "2026-10"}, "budget_not_current"),
        ({"checked_at": PREPARED - timedelta(seconds=1)}, "budget_not_current"),
        ({"checked_at": SEND + timedelta(seconds=1)}, "budget_not_current"),
    ]:
        result = check_send(edition(), context(budget=budget.model_copy(update=change)))
        assert not result.can_send and reason in result.reasons
    for value in ["NaN", "Infinity", "-1"]:
        with pytest.raises(ValidationError):
            BudgetState.model_validate(budget.model_dump() | {"reserved_krw": value})


def test_synthetic_dry_run_and_source_expiry_cannot_send():
    assert not check_send(build_morning(inputs(), now=PREPARED), context()).can_send
    result = build_morning(inputs(live=True), now=PREPARED, source_expires_at=SEND)
    assert not check_send(result, context()).can_send
    assert (
        build_morning(inputs(), now=PREPARED, source_expires_at=PREPARED).status
        == "failed"
    )


def test_price_decimal_is_preserved_and_ten_instruments_still_only_three_news():
    data = inputs(live=True)
    quote = data.market.quotes[0]
    changed = quote.model_copy(
        update={
            "latest": quote.latest.model_copy(
                update={
                    "close": Decimal("25100.125"),
                    "provider_change": Decimal("100.125"),
                }
            )
        }
    )
    result = edition(
        market=data.market.model_copy(
            update={"quotes": (changed, *data.market.quotes[1:])}
        )
    )
    assert "25,100.125원" in result.body
    instruments = (
        *data.instruments,
        *(
            data.instruments[0].model_copy(
                update={"code": f"60000{i}", "isin": f"KR{60000 + i:010d}"}
            )
            for i in range(7)
        ),
    )
    codes = tuple(i.code for i in instruments)
    quotes = (
        *data.market.quotes,
        *(
            data.market.quotes[0].model_copy(update={"code": i.code})
            for i in instruments[3:]
        ),
    )
    market = Collection.model_validate(
        data.market.model_dump() | {"quotes": quotes, "requested_codes": codes}
    )
    result = edition(instruments=instruments, market=market)
    assert (
        result.status == "ready" and result.price_count == 10 and result.news_count == 3
    )
    assert result.body.count("AI 요약:") == 1
    assert check_send(result, context(active_codes=codes)).can_send


def test_cli_file_defaults_to_actual_clock_and_does_not_replay_expired_day(
    tmp_path, capsys, monkeypatch
):
    from xfolio.newsletter import cli as newsletter_cli

    class Clock:
        @staticmethod
        def now(tz):
            return at(DAY, 9).astimezone(tz)

    monkeypatch.setattr(newsletter_cli, "datetime", Clock)
    input_file = tmp_path / "input.json"
    input_file.write_text(inputs(live=True).model_dump_json(), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["newsletter-preview", "--inputs-file", str(input_file), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["edition"]["status"] == "failed"
    assert "preparation_time_invalid" in report["edition"]["reasons"]


@pytest.mark.parametrize(
    "scenario,status",
    [
        ("news", "ready"),
        ("zero", "ready"),
        ("partial", "partial"),
        ("failed", "failed"),
    ],
)
def test_cli_no_network_or_database(scenario, status, capsys):
    if scenario == "failed":
        with pytest.raises(SystemExit) as exc:
            main(["newsletter-preview", "--scenario", scenario, "--json"])
        assert exc.value.code == 1
    else:
        main(["newsletter-preview", "--scenario", scenario, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == report["database_writes"] == 0
    assert not report["can_send"] and report["edition"]["status"] == status


def test_cli_files_and_invalid_input_do_not_leak_values(tmp_path, capsys):
    input_file = tmp_path / "input.json"
    context_file = tmp_path / "context.json"
    input_file.write_text(inputs(live=True).model_dump_json(), encoding="utf-8")
    context_file.write_text(context().model_dump_json(), encoding="utf-8")
    main(
        [
            "newsletter-preview",
            "--inputs-file",
            str(input_file),
            "--context-file",
            str(context_file),
            "--prepared-at",
            PREPARED.isoformat(),
            "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["send_check"]["can_send"] and not report["can_send"]
    assert report["check_scope"] == "local_inputs_only"
    input_file.write_text('{"secret":"NEVER_OUTPUT_THIS"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["newsletter-preview", "--inputs-file", str(input_file)])
    assert "NEVER_OUTPUT_THIS" not in capsys.readouterr().out
