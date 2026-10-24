"""공통 가상 분석 경로의 요청 경계와 기계 검사를 확인한다."""

import json

import httpx
import pytest
from openai import OpenAI

from xfolio.analysis import (
    DEFAULT_MODEL,
    INSTRUCTIONS,
    MODEL_PRICES,
    analyze_synthetic,
    usage_cost_usd,
)
from xfolio.cli import main


def response(model, *, selected=True, summary=None, evidence=None):
    source = "Fictional Office announced on 2026-10-23 that 2026-09 CPI rose 2.5%."
    content = {
        "selected": selected,
        "reason_ko": "주체·발표일·대상 기간이 확인됩니다.",
        "summary_ko": summary
        if summary is not None
        else "가상 기관이 2026-10-23에 발표한 2026-09 CPI는 2.5% 상승했습니다.",
        "source_id": "case-1",
        "evidence": evidence if evidence is not None else source,
    }
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(content),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }


@pytest.mark.parametrize("model", tuple(MODEL_PRICES))
def test_same_contract_and_model_cost(model):
    source = "Fictional Office announced on 2026-10-23 that 2026-09 CPI rose 2.5%."
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url.path == "/v1/responses"
        assert body["instructions"] == INSTRUCTIONS
        assert body["model"] == model
        assert body["store"] is False
        assert body["tools"] == []
        assert body["text"]["format"]["strict"] is True
        return httpx.Response(200, json=response(model))

    with OpenAI(
        api_key="placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        report = analyze_synthetic(
            client,
            source_id="case-1",
            source_text=source,
            required_literals=("2026-09", "2.5%"),
            expected_selected=True,
            model=model,
        )
    assert len(seen) == 1
    assert report["status"] == "mechanical_checks_passed"
    assert report["human_review_required"] is True
    input_price, output_price = MODEL_PRICES[model]
    assert report["cost_usd"] == pytest.approx(
        (100 * input_price + 50 * output_price) / 1e6
    )


@pytest.mark.parametrize(
    "change",
    [
        {"selected": False, "summary": "보류인데 문장이 있습니다."},
        {"summary": "가상 기관은 999% 상승을 발표했습니다."},
        {"evidence": "없는 근거"},
    ],
)
def test_unverifiable_output_is_held(change):
    source = "Fictional Office announced on 2026-10-23 that 2026-09 CPI rose 2.5%."
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=response("gpt-6-luna", **change))
    )
    with OpenAI(
        api_key="placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=transport),
    ) as client:
        report = analyze_synthetic(
            client,
            source_id="case-1",
            source_text=source,
            required_literals=("2.5%",),
            model="gpt-6-luna",
        )
    assert report["status"] == "failed"
    assert not all(report["checks"].values())


def test_cli_dry_run_does_not_construct_client(monkeypatch, capsys):
    monkeypatch.setattr("xfolio.cli.OpenAI", lambda **kwargs: pytest.fail("network"))
    main(["ai-preview"])
    report = json.loads(capsys.readouterr().out)
    assert DEFAULT_MODEL == "gpt-6-luna"
    assert report["model"] == DEFAULT_MODEL
    assert report["network_requests"] == 0
    assert report["synthetic"] is True
    assert report["can_publish"] is False


def test_luna_cache_write_cost_is_counted():
    usage = {
        "input_tokens": 8598,
        "output_tokens": 157,
        "total_tokens": 8755,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 4393},
    }
    assert usage_cost_usd(usage, "gpt-6-luna") == pytest.approx(0.001048125)
