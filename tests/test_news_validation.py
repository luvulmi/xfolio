import unicodedata
from types import SimpleNamespace

import pytest
from test_news_workflow import Client, MemoryStore, WorkflowError, bundle, run

from xfolio.bls import RELEASE_URL
from xfolio.news_validation import (
    DraftValidationError,
    cpi_claim_contract,
    cpi_weighted_length,
    validate_cpi_generation,
)


@pytest.mark.parametrize(
    "addition",
    [
        "하지 않았다",
        " 이후 주가 상승을 유발했다",
        " 매수를 권한다",
        "가 예상된다",
        "가 아니다",
    ],
)
def test_same_numbers_with_new_meaning_are_charged_and_rejected(addition):
    def mutate(response):
        response["output"]["claims"][0]["text_ko"] += addition
        return response

    store = MemoryStore()
    with pytest.raises(WorkflowError, match="OUTPUT_SEMANTIC_MISMATCH"):
        run(client=Client(mutate), store=store)
    assert store.saved == []
    assert len(store.reservations) == 1
    assert store.failures[-1] == "OUTPUT_SEMANTIC_MISMATCH"


def test_known_url_nfc_hangul_and_exact_length_boundary():
    assert cpi_weighted_length("a" * 256 + " " + RELEASE_URL) == 280
    assert cpi_weighted_length("a" * 257 + " " + RELEASE_URL) == 281
    composed = "미국 " + RELEASE_URL
    assert cpi_weighted_length(composed) == 28
    assert cpi_weighted_length(unicodedata.normalize("NFD", composed)) == 28


@pytest.mark.parametrize(
    "body,code",
    [
        ("👨‍👩‍👧‍👦 ", "UNSUPPORTED_TEXT_CHARACTER"),
        ("a\x00 ", "UNSUPPORTED_TEXT_CHARACTER"),
        ("https://example.com ", "UNSUPPORTED_POST_URL"),
        ("www.example.com ", "UNSUPPORTED_POST_URL"),
    ],
)
def test_unsupported_content_is_rejected_instead_of_undercounted(body, code):
    with pytest.raises(DraftValidationError, match=code):
        cpi_weighted_length(body + RELEASE_URL)


def test_valid_semantics_cannot_bypass_complete_post_length():
    source = bundle()
    required = cpi_claim_contract(
        source.event.claims, source.event.period_or_transaction
    )
    required[0]["required_literals"][2] = "1" * 280 + "%"
    output = SimpleNamespace(
        claims=[
            SimpleNamespace(text_ko=" ".join(c["required_literals"])) for c in required
        ]
    )
    with pytest.raises(DraftValidationError, match="X_WEIGHTED_LENGTH_EXCEEDED"):
        validate_cpi_generation(output, required, source.source.published_at)
