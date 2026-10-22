"""Offline SDK contract probe. Synthetic inputs; no network or real API keys."""

import inspect
import json
from importlib.metadata import version
from typing import Literal

import httpx
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text_ko: str
    source_id: str
    evidence: str


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["macro", "sector", "company"]
    selected: bool
    claims: list[Claim]


def main() -> None:
    source = {"sample_01": "Fictional company revenue: USD 10 billion, Q3."}
    valid = {
        "category": "company",
        "selected": True,
        "claims": [
            {
                "text_ko": "Fictional company revenue: USD 10 billion, Q3.",
                "source_id": "sample_01",
                "evidence": source["sample_01"],
            }
        ],
    }
    Draft.model_validate(valid)
    rejected = 0
    for invalid in (
        {**valid, "selected": "true"},
        {**valid, "category": "stock_tip"},
        {**valid, "unapproved_field": "value"},
    ):
        try:
            Draft.model_validate(invalid)
        except ValidationError:
            rejected += 1
    assert rejected == 3

    wrong = json.loads(json.dumps(valid))
    wrong["claims"][0]["text_ko"] = "Revenue: USD 999 billion, Q3."
    parsed_wrong = Draft.model_validate(wrong)
    assert "999" in parsed_wrong.claims[0].text_ko
    # Schema acceptance is not evidence of factual correctness.
    wrong["claims"][0]["evidence"] = "Invented evidence"
    assert not any(wrong["claims"][0]["evidence"] in text for text in source.values())

    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "gpt-5.4-mini"
        assert body["store"] is False
        assert body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 1000
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        assert body.get("tools", []) == []
        return httpx.Response(
            200,
            json={
                "id": "resp_offline_synthetic",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "gpt-5.4-mini",
                "output": [
                    {
                        "id": "msg_synthetic",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(valid),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "total_tokens": 140,
                },
            },
        )

    with OpenAI(
        api_key="offline-placeholder",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        result = client.responses.parse(
            model="gpt-5.4-mini",
            input="Synthetic contract probe, not a real news article.",
            text_format=Draft,
            store=False,
            reasoning={"effort": "none"},
            max_output_tokens=1000,
        )
        assert result.output_parsed == Draft.model_validate(valid)
        assert result.usage.output_tokens == 40
        assert len(requests) == 1
        assert "text_format" in inspect.signature(client.responses.parse).parameters

    print(
        json.dumps(
            {"versions": {n: version(n) for n in ["openai", "pydantic", "httpx"]}}
        )
    )
    print("PASS: strict schema rejects 3 invalid payloads")
    print("PASS: schema accepts factual error; evidence check remains necessary")
    print(
        "PASS: SDK request schema, no storage, reasoning, output limit, mocked parsing"
    )
    print("NO NETWORK; NO REAL MODEL OUTPUT; usage is synthetic")


if __name__ == "__main__":
    main()
