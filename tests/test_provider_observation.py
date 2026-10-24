import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xfolio.bls import BLSError
from xfolio.news_models import NewsCollection

SPEC = importlib.util.spec_from_file_location(
    "provider_observation",
    Path(__file__).parents[1] / "scripts/experiments/provider_observation.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 10, 25, 1, 2, 3, 456, tzinfo=UTC)


def test_default_no_network_no_files(tmp_path):
    report = probe.observe(output=tmp_path, now=NOW)
    assert report["mode"] == "dry_run"
    assert list(tmp_path.iterdir()) == []


def test_daily_budget_and_failure_retained_without_body_storage(tmp_path, monkeypatch):
    calls = []

    def official(**kwargs):
        raise BLSError("http_403")

    def news(**kwargs):
        calls.append(kwargs)
        assert kwargs["end"].microsecond == 0
        return NewsCollection(
            status="partial",
            window_start=kwargs["start"],
            window_end=kwargs["end"],
            collected_at=kwargs["end"],
            requests=6,
            error="page_budget",
        )

    monkeypatch.setattr(probe, "inspect_bls", official)
    monkeypatch.setattr(probe, "collect_news", news)
    for _ in range(2):
        result = probe.observe(
            run=True, token="private-test-token", output=tmp_path, now=NOW
        )
        assert result["bls"]["error"] == "http_403"
        assert result["marketaux"]["checkpoint_eligible"] is False
    with pytest.raises(ValueError, match="daily_observation_budget_exhausted"):
        probe.observe(run=True, token="private-test-token", output=tmp_path, now=NOW)
    assert len(calls) == 2
    for path in tmp_path.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "private-test-token" not in text
        assert json.loads(text)["can_publish"] is False
