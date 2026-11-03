"""가짜 시계로 슬롯 전/정시/지각·중복·실패를 검증하며 실제 API를 호출하지 않는다."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "finnhub_slot_probe",
    Path(__file__).parents[1] / "scripts/experiments/finnhub_slot_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
SLOT = datetime(2026, 11, 4, 8, tzinfo=probe.KST)


class Clock:
    def __init__(self, current):
        self.current = current
        self.elapsed = 0

    def now(self):
        return self.current

    def sleep(self, seconds):
        assert 0 <= seconds <= 1
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds


def setup(tmp_path, monkeypatch, when):
    monkeypatch.setattr(probe, "EVIDENCE_ROOT", tmp_path)
    return tmp_path / "slot" / "metadata.json", Clock(when)


def execute(output, clock, *, runner=None, live=True):
    return probe.observe(
        SLOT,
        output,
        live=live,
        now=clock.now,
        sleep=clock.sleep,
        monotonic=lambda: clock.elapsed,
        runner=runner,
    )


def forbidden(output):
    pytest.fail("this case must not invoke the API runner")


def test_plan_never_waits_or_creates_files(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT - timedelta(hours=2))
    report = execute(output, clock, runner=forbidden, live=False)
    assert report["status"] == "plan" and report["network_requests"] == 0
    assert clock.elapsed == 0 and not output.parent.exists()


def test_far_early_does_not_claim_or_write(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT - timedelta(seconds=91))
    assert execute(output, clock, runner=forbidden)["status"] == "too_early"
    assert clock.elapsed == 0 and not output.parent.exists()


def test_early_waits_then_records_actual_request(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT - timedelta(seconds=15))
    calls = []

    def runner(sample_path):
        calls.append(sample_path)
        assert clock.now() == SLOT
        return {
            "requested_at_utc": clock.now().astimezone(UTC).isoformat(),
            "api_calls": 1,
            "development_selected_ids": [12],
        }

    report = execute(output, clock, runner=runner)
    assert len(calls) == 1 and clock.elapsed == 15
    assert report["status"] == "observed" and report["historical_snapshot_verified"]
    assert report["request_offset_seconds"] == 0
    assert output.with_suffix(".claim").exists()
    assert json.loads(output.read_text(encoding="utf-8"))["sample"] == report["sample"]
    assert execute(output, clock, runner=forbidden)["status"] == "already_recorded"


@pytest.mark.parametrize("offset", [60, 3600, 86400])
def test_late_is_zero_calls_and_not_backfilled(tmp_path, monkeypatch, offset):
    output, clock = setup(tmp_path, monkeypatch, SLOT + timedelta(seconds=offset))
    report = execute(output, clock, runner=forbidden)
    assert report["status"] == "missed_window" and report["api_calls"] == 0
    assert not report["historical_snapshot_verified"]
    assert not output.with_suffix(".claim").exists()


def test_actual_api_start_rechecked_after_setup(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT + timedelta(seconds=59))

    def runner(sample_path):
        return {
            "requested_at_utc": (SLOT + timedelta(seconds=61)).isoformat(),
            "api_calls": 1,
        }

    result = execute(output, clock, runner=runner)
    assert result["status"] == "late_request"
    assert not result["historical_snapshot_verified"]


def test_failure_retains_claim_and_omits_exception_secret(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT)

    def runner(sample_path):
        raise RuntimeError("secret_key_that_must_not_be_saved")

    report = execute(output, clock, runner=runner)
    assert report["status"] == "probe_failed" and report["api_calls"] is None
    assert "secret_key_that" not in output.read_text(encoding="utf-8")
    assert output.with_suffix(".claim").exists()
    # 중간 종료로 결과가 없는 경우에도 claim이 중복 조회를 막는다.
    output.unlink()
    assert execute(output, clock, runner=forbidden)["status"] == "already_claimed"


@pytest.mark.parametrize(
    "slot", [SLOT.replace(tzinfo=None), SLOT.replace(hour=7), SLOT + timedelta(days=3)]
)
def test_bad_slot_rejected(slot, tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT)
    with pytest.raises(ValueError):
        probe.observe(slot, output, now=clock.now, runner=forbidden)


def test_output_escape_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "EVIDENCE_ROOT", tmp_path / "inside")
    with pytest.raises(ValueError):
        probe.observe(SLOT, tmp_path / "outside.json", live=True, runner=forbidden)


def test_late_parallel_run_preserves_existing_claim(tmp_path, monkeypatch):
    output, clock = setup(tmp_path, monkeypatch, SLOT + timedelta(minutes=2))
    output.parent.mkdir(parents=True)
    output.with_suffix(".claim").write_text(
        "first run owns this slot", encoding="utf-8"
    )
    result = execute(output, clock, runner=forbidden)
    assert result["status"] == "already_claimed"
    assert not output.exists()


def test_slot_receives_real_probe_freshness_without_network(tmp_path, monkeypatch):
    root = tmp_path / "tasks/verification/assets/news_samples"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(probe, "EVIDENCE_ROOT", root)
    runner = probe.load_runner()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return SLOT.astimezone(tz or UTC)

    monkeypatch.setitem(runner.__globals__, "datetime", FrozenDateTime)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": 100,
                    "headline": "Nvidia revenue rises",
                    "source": "CNBC",
                    "datetime": int((SLOT - timedelta(hours=1)).timestamp()),
                    "url": "https://www.cnbc.com/2026/11/04/nvidia-results.html",
                }
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe.observe(
            SLOT,
            root / "slot/metadata.json",
            live=True,
            now=lambda: SLOT,
            runner=lambda output: runner(
                output, client=client, api_key="synthetic_test_key"
            ),
        )
    assert report["status"] == "observed" and len(calls) == 1
    assert report["sample"]["within_24h_of_query"] == 1
    assert report["sample"]["development_selected_ids"] == [100]
    assert report["sample"]["publication_age_is_provider_delay"] is False
    assert (root / "slot/metadata_sample.json").exists()
