import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from xfolio.news_generation import (
    INSTRUCTIONS,
    OpenAIGenerationClient,
    estimate_input_tokens,
)
from xfolio.news_workflow import GeneratedNews, WorkflowError


def response(**changes):
    return SimpleNamespace(
        **(
            {
                "model": "gpt-6-luna",
                "status": "completed",
                "usage": SimpleNamespace(
                    input_tokens=100, output_tokens=50, total_tokens=150
                ),
                "output_parsed": {
                    "source_id": "fixture",
                    "content_version": "v1",
                    "claims": [
                        {
                            "claim_id": "claim-0",
                            "text_ko": "가상 요약",
                            "evidence_span": "fixture evidence",
                        }
                    ],
                },
            }
            | changes
        )
    )


class SDK:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or response()
        self.responses = self
        self.options = None

    def with_options(self, **kwargs):
        self.options = kwargs
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def generate(sdk, **changes):
    return OpenAIGenerationClient(sdk).generate(
        **(
            {
                "model": "gpt-6-luna",
                "input_json": '{"source_id":"fixture"}',
                "max_output_tokens": 600,
                "max_input_tokens": 8000,
            }
            | changes
        )
    )


def test_injected_responses_parser_uses_closed_tools_and_explicit_caps():
    sdk = SDK()
    result = generate(sdk)
    assert result.output.claims[0].text_ko == "가상 요약"
    assert (result.input_tokens, result.output_tokens) == (100, 50)
    assert sdk.options == {"max_retries": 0, "timeout": 30}
    request = sdk.calls[0]
    assert request["model"] == "gpt-6-luna"
    assert request["store"] is False
    assert request["tools"] == []
    assert request["reasoning"] == {"effort": "none"}
    assert request["text_format"] is GeneratedNews
    assert request["max_output_tokens"] == 600
    assert request["instructions"] == INSTRUCTIONS


def test_input_bound_includes_instructions_schema_and_protocol_before_request():
    payload = json.dumps({"text": "가상" * 10}, ensure_ascii=False)
    bare = len(payload.encode("utf-8"))
    assert (
        estimate_input_tokens(payload) > bare + len(INSTRUCTIONS.encode("utf-8")) + 512
    )
    sdk = SDK()
    with pytest.raises(WorkflowError, match="INPUT_BUDGET_EXCEEDED"):
        generate(
            sdk, input_json=payload, max_input_tokens=estimate_input_tokens(payload) - 1
        )
    assert sdk.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "other"},
        {"max_output_tokens": True},
        {"max_input_tokens": 16001},
        {"max_input_tokens": 255},
        {"max_output_tokens": 99},
    ],
)
def test_invalid_limits_or_unpriced_model_do_not_call_sdk(changes):
    sdk = SDK()
    with pytest.raises(WorkflowError):
        generate(sdk, **changes)
    assert sdk.calls == []


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"model": "gpt-6-luna-unverified-snapshot"}, "UNEXPECTED_RESPONSE_MODEL"),
        ({"model": "other-model"}, "UNEXPECTED_RESPONSE_MODEL"),
        ({"status": "incomplete"}, "GENERATION_NOT_COMPLETED"),
        ({"output_parsed": None}, "GENERATION_NOT_COMPLETED"),
        ({"usage": None}, "GENERATION_USAGE_INVALID"),
        (
            {
                "usage": SimpleNamespace(
                    input_tokens=True, output_tokens=5, total_tokens=6
                )
            },
            "GENERATION_USAGE_INVALID",
        ),
        (
            {
                "usage": SimpleNamespace(
                    input_tokens=-1, output_tokens=5, total_tokens=4
                )
            },
            "GENERATION_USAGE_INVALID",
        ),
        (
            {
                "usage": SimpleNamespace(
                    input_tokens=100, output_tokens=5, total_tokens=109
                )
            },
            "GENERATION_USAGE_INVALID",
        ),
        (
            {
                "usage": SimpleNamespace(
                    input_tokens=8001, output_tokens=5, total_tokens=8006
                )
            },
            "USAGE_EXCEEDS_RESERVED_MAXIMUM",
        ),
        (
            {
                "usage": SimpleNamespace(
                    input_tokens=100, output_tokens=601, total_tokens=701
                )
            },
            "USAGE_EXCEEDS_RESERVED_MAXIMUM",
        ),
    ],
)
def test_response_model_completion_and_strict_usage_are_verified(changes, code):
    with pytest.raises(WorkflowError, match=code):
        generate(SDK(response(**changes)))


def test_unexpected_output_shape_is_not_accepted():
    with pytest.raises(ValidationError):
        generate(SDK(response(output_parsed={"text": "schema mismatch"})))
