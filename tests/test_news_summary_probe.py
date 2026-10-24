"""네트워크 없이 가상 요약 시험의 계량·실패·비밀 보호 경계를 검증한다."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

SPEC = importlib.util.spec_from_file_location(
    "news_summary_probe",
    Path(__file__).resolve().parents[1] / "scripts/experiments/news_summary_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def sample_response(**updates):
    sample = probe.SAMPLES[0]
    content = {
        "selected": True,
        "reason_ko": "주체와 발표일 및 대상 기간이 확인됩니다.",
        "summary_ko": "가상 통계국 2026-10-10 발표: 2026-09 CPI 전년비 2.5% 상승.",
        "source_id": sample.source_id,
        "evidence": sample.text,
    }
    content.update(updates)
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": probe.MODEL,
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


def execute(payload=None, status=200):
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url.path == "/v1/responses"
        assert body["model"] == probe.MODEL
        assert body["instructions"] == probe.INSTRUCTIONS
        assert body["store"] is False
        assert body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 600
        assert body["tools"] == []
        assert body["text"]["format"]["strict"] is True
        return httpx.Response(status, json=payload)

    with OpenAI(
        api_key="secret-never-print",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        report = probe.probe(client, probe.SAMPLES[0])
    assert len(seen) == 1
    return report


def test_normal_usage_and_cost():
    report = execute(sample_response())
    assert report["status"] == "mechanical_checks_passed"
    assert report["usage"]["total_tokens"] == 150
    assert report["cost_usd"] == pytest.approx(0.0003)
    assert report["human_review_required"] is True
    assert report["prompt_version"] == "synthetic_summary_v2_scope_conditions"
    assert datetime.fromisoformat(
        report["observed_at_utc"]
    ).utcoffset() == UTC.utcoffset(None)


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 100, "output_tokens": 50, "total_tokens": 151},
        {"input_tokens": -100, "output_tokens": 50, "total_tokens": -50},
        {"input_tokens": "100", "output_tokens": 50, "total_tokens": 150},
        {"input_tokens": True, "output_tokens": 50, "total_tokens": 51},
        [100, 50, 150],
        "invalid usage",
        None,
    ],
)
def test_invalid_usage_preserved_without_cost(usage):
    payload = sample_response()
    payload["usage"] = usage
    report = execute(payload)
    assert report["status"] == "failed"
    assert report["usage"] == usage
    assert report["cost_usd"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": "unknown"},
        {"evidence": "invented evidence"},
        {"summary_ko": "가상 통계국 2026-10-10 발표: 2026-09 CPI 999% 상승."},
        {"selected": False, "summary_ko": "보류인데 요약이 남음"},
    ],
)
def test_invalid_evidence_source_or_summary(change):
    report = execute(sample_response(**change))
    assert report["status"] == "failed"
    assert not all(report["checks"].values())
    assert report["usage"]["total_tokens"] == 150


@pytest.mark.parametrize(
    "case", ["incomplete", "refused", "missing_usage", "invalid_schema"]
)
def test_incomplete_refused_missing_usage_and_parse_failure(case):
    payload = sample_response()
    if case == "incomplete":
        payload.update(status="incomplete", output=[])
    elif case == "refused":
        payload["output"][0]["content"] = [{"type": "refusal", "refusal": "거절"}]
    elif case == "missing_usage":
        payload.pop("usage")
    else:
        payload["output"][0]["content"][0]["text"] = '{"selected": "wrong"}'
    report = execute(payload)
    assert report["status"] == "failed"
    if case != "missing_usage":
        assert report["usage"]["total_tokens"] == 150


def test_api_error_does_not_leak_secret():
    report = execute(
        {
            "error": {
                "message": "secret-never-print",
                "type": "secret-never-print",
                "code": "secret-never-print",
            }
        },
        400,
    )
    assert report["status"] == "failed"
    assert "secret-never-print" not in json.dumps(report)
    assert report["error_type"] == "BadRequestError"
    assert report["status_code"] == 400
    assert report["error_code"] is None
    assert report["api_error_type"] is None
    assert report["batch_stop"] is True


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, None])
def test_fatal_api_error_stops_batch_after_one_request(monkeypatch, capsys, status):
    requests = []

    def handle(request):
        requests.append(request)
        if status is None:
            raise httpx.ConnectError("secret-never-print", request=request)
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "secret-never-print",
                    "code": "credit_balance_exhausted",
                    "type": "insufficient_quota",
                }
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "offline-placeholder")
    monkeypatch.setattr(
        probe,
        "OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        ),
    )
    assert probe.main(["--run"]) == 1
    output = capsys.readouterr().out
    report, summary = [json.loads(line) for line in output.splitlines()]
    assert len(requests) == 1
    assert report["status_code"] == status
    assert report["error_code"] == (
        "credit_balance_exhausted" if status is not None else None
    )
    assert report["api_error_type"] == (
        "insufficient_quota" if status is not None else None
    )
    assert summary["calls"] == 1
    assert summary["planned_calls"] == 6
    assert summary["skipped_calls"] == 5
    assert summary["batch_stopped"] is True
    assert summary["known_usage_cost_usd"] == 0
    assert summary["usage_complete"] is False
    assert summary["unknown_calls"] == summary["missing_usage_calls"] == 1
    assert "secret-never-print" not in output


def test_parsing_failure_continues_and_preserves_usage(monkeypatch, capsys):
    requests = []
    payload = sample_response()
    payload["output"][0]["content"][0]["text"] = '{"selected": "wrong"}'

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setenv("OPENAI_API_KEY", "offline-placeholder")
    monkeypatch.setattr(
        probe,
        "OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        ),
    )
    assert probe.main(["--run"]) == 1
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(requests) == 6
    assert all(item["usage"] == payload["usage"] for item in reports[:-1])
    assert reports[-1]["usage_complete"] is True
    assert reports[-1]["known_usage_cost_usd"] == pytest.approx(0.0018)
    assert reports[-1]["unknown_calls"] == reports[-1]["missing_usage_calls"] == 0
    assert reports[-1]["skipped_calls"] == 0


def test_dry_run_and_missing_key_never_construct_client(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        probe, "OpenAI", lambda **kwargs: pytest.fail("network client constructed")
    )
    assert probe.main([]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["network_requests"] == 0
    assert dry["config"]["prompt_version"] == probe.PROMPT_VERSION
    assert len(dry["samples"]) == 6
    assert sum(item["expected_selected"] for item in dry["samples"]) == 4
    assert probe.main(["--run"]) == 2
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
