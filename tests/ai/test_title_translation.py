"""제목만 전달·정산·실패/수치/출처 경계를 외부 호출 없이 검증한다."""

import json
import re
import socket

import pytest

from tests.ai.test_news_generation import SDK, response
from tests.news.test_newsletter_news import NOW, Budget, limits, link
from xfolio.ai.title_translation import (
    OpenAITitleTranslationClient,
    TranslatedTitle,
    TranslatedTitles,
    translate_titles,
)
from xfolio.ai.workflow import WorkflowError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


class TitleBudget(Budget):
    def reserve(self, *args, **kwargs):
        assert kwargs["purpose"] == "news_title_translation"
        return super().reserve(*args)


class FakeTitleAI:
    def __init__(self):
        self.calls = []

    def translate(self, **kwargs):
        self.calls.append(kwargs)
        rows = json.loads(kwargs["input_json"])["titles"]
        return {
            "output": {
                "titles": [
                    row
                    | {
                        "title_ko": "가상 한국어 제목 "
                        + " ".join(re.findall(r"\d+(?:[.,]\d+)*%?", row["title"]))
                    }
                    for row in rows
                ]
            },
            "input_tokens": 100,
            "output_tokens": 60,
        }


def test_batch_translates_only_selected_headlines_and_settles_once():
    ai, budget = FakeTitleAI(), TitleBudget()
    rows = (link(),)
    translated = translate_titles(
        rows, client=ai, store=budget, limits=limits(), now=NOW
    )
    assert len(ai.calls) == budget.reserved == budget.confirmed == 1
    request = json.loads(ai.calls[0]["input_json"])
    assert set(request) == {"titles"}
    assert set(request["titles"][0]) == {"source_id", "content_version", "title"}
    assert translated[0].title == rows[0].title and "한국어" in translated[0].title_ko


def test_empty_selection_and_budget_failure_never_call_ai():
    ai, budget = FakeTitleAI(), TitleBudget(fail=True)
    assert translate_titles((), client=ai, store=budget, limits=limits(), now=NOW) == ()
    with pytest.raises(ValueError, match="budget"):
        translate_titles((link(),), client=ai, store=budget, limits=limits(), now=NOW)
    assert not ai.calls


def test_source_mismatch_charges_known_usage_but_rejects_translation():
    budget = TitleBudget()

    class Wrong(FakeTitleAI):
        def translate(self, **kwargs):
            result = super().translate(**kwargs)
            result["output"]["titles"][0]["source_id"] = "wrong"
            return result

    with pytest.raises(WorkflowError, match="SOURCE_MISMATCH"):
        translate_titles(
            (link(),), client=Wrong(), store=budget, limits=limits(), now=NOW
        )
    assert budget.confirmed == budget.failed == 1


def test_unknown_api_result_keeps_reservation_and_does_not_retry():
    calls, budget = [], TitleBudget()

    class Broken:
        def translate(self, **kwargs):
            calls.append(1)
            raise RuntimeError("secret external exception")

    with pytest.raises(WorkflowError, match="RESULT_UNKNOWN") as exc:
        translate_titles(
            (link(),), client=Broken(), store=budget, limits=limits(), now=NOW
        )
    assert "secret" not in str(exc.value)
    assert len(calls) == budget.failed == budget.reserved == 1 and not budget.confirmed


@pytest.mark.parametrize(
    "title_ko",
    [
        "English only",
        "수치가 4% 하락",
        "수치가 3% 하락 https://example.org",
        "수치가 3%\n하락",
    ],
)
def test_malformed_or_changed_number_is_rejected(title_ko):
    with pytest.raises(ValueError):
        TranslatedTitle(
            source_id="story",
            content_version="v1",
            title="Stocks fall 3%",
            title_ko=title_ko,
        )


def test_structured_sdk_request_has_no_tools_and_no_automatic_retry():
    original = link()
    translated = TranslatedTitle(
        source_id=original.source_id,
        content_version=original.content_version,
        title=original.title,
        title_ko="가상 한국어 제목 "
        + " ".join(re.findall(r"\d+(?:[.,]\d+)*%?", original.title)),
    )
    sdk = SDK(response(output_parsed=TranslatedTitles(titles=(translated,))))
    result = translate_titles(
        (original,),
        client=OpenAITitleTranslationClient(sdk),
        store=TitleBudget(),
        limits=limits(),
        now=NOW,
    )
    assert result[0] == translated
    request = sdk.calls[0]
    assert request["text_format"] is TranslatedTitles and request["store"] is False
    assert request["tools"] == [] and sdk.options == {"max_retries": 0, "timeout": 20}


@pytest.mark.parametrize(
    ("title", "title_ko"),
    [
        (
            "Fear gauge surges most since April",
            "공포지수가 4월 이후 가장 큰 폭으로 상승",
        ),
        ("Stocks rise 3% in November", "주가가 11월에 3% 상승"),
    ],
)
def test_named_month_translation_preserves_month_and_numbers(title, title_ko):
    assert (
        TranslatedTitle(
            source_id="story", content_version="v1", title=title, title_ko=title_ko
        ).title_ko
        == title_ko
    )


@pytest.mark.parametrize(
    "title_ko",
    ["공포지수가 5월 이후 상승", "공포지수가 4월 이후 3% 상승", "공포지수가 4% 상승"],
)
def test_month_conversion_rejects_changed_month_or_added_number(title_ko):
    with pytest.raises(ValueError):
        TranslatedTitle(
            source_id="story",
            content_version="v1",
            title="Fear gauge surges most since April",
            title_ko=title_ko,
        )


def test_month_conversion_does_not_allow_reordered_numeric_values():
    with pytest.raises(ValueError):
        TranslatedTitle(
            source_id="story",
            content_version="v1",
            title="Stocks rise 3% as yields fall 2% in April",
            title_ko="4월 주가가 2% 상승하고 금리는 3% 하락",
        )
