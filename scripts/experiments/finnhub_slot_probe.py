"""평일08:00 KST의 1회 관측. 지각/중복을 소급 성공으로 만들지 않는다."""

import argparse
import importlib.util
import json
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[2] / "tasks/verification/assets/news_samples"
)


def utc_now():
    return datetime.now(UTC)


def check_slot(slot):
    if slot.tzinfo is None:
        raise ValueError("slot requires an explicit timezone")
    local = slot.astimezone(KST)
    if (local.hour, local.minute, local.second, local.microsecond) != (8, 0, 0, 0):
        raise ValueError("slot must be 08:00:00 KST")
    if local.weekday() >= 5:
        raise ValueError("weekday slots only")


def timing(now, slot):
    delta = (now - slot).total_seconds()
    return "early" if delta < 0 else "on_time" if delta < 60 else "late"


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "finnhub_slot_news", Path(__file__).with_name("finnhub_news_probe.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_probe


def write_new(output, report):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def observe(
    slot,
    output,
    *,
    live=False,
    now=utc_now,
    sleep=time.sleep,
    monotonic=time.monotonic,
    runner=None,
):
    check_slot(slot)
    output = output.resolve()
    if not output.is_relative_to(EVIDENCE_ROOT.resolve()):
        raise ValueError("output must stay under news_samples")
    started = now()
    report = {
        "slot_at_kst": slot.astimezone(KST).isoformat(),
        "started_at_utc": started.isoformat(),
        "on_time_window_seconds": 60,
        "historical_snapshot_verified": False,
        "telegram_sent": False,
        "api_calls": 0,
    }
    if not live:
        return {
            **report,
            "status": "plan",
            "network_requests": 0,
            "timing_now": timing(started, slot),
            "max_early_wait_seconds": 90,
        }
    if output.exists():
        return {**report, "status": "already_recorded"}
    claim = output.with_suffix(".claim")
    if claim.exists():
        return {**report, "status": "already_claimed", "network_requests": 0}

    # 예약보다 크게 이른 수동 실행은 대기/통신 없이 종료한다.
    if (slot - started).total_seconds() > 90:
        return {**report, "status": "too_early", "network_requests": 0}
    deadline = monotonic() + 90
    while now() < slot and monotonic() < deadline:
        sleep(max(0, min(1, (slot - now()).total_seconds())))
    attempt = now()
    if timing(attempt, slot) != "on_time":
        report.update(
            status="missed_window",
            checked_at_utc=attempt.isoformat(),
            timing=timing(attempt, slot),
            network_requests=0,
        )
        write_new(output, report)
        return report

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with claim.open("x", encoding="utf-8") as handle:
            handle.write(attempt.isoformat() + "\n")
    except FileExistsError:
        return {**report, "status": "already_claimed", "network_requests": 0}

    # claim은 완료/오류 후에도 남겨 같은 슬롯 재조회로 증거를 덮지 않는다.
    sample_path = output.with_name(output.stem + "_sample.json")
    try:
        sample = (runner or load_runner())(sample_path)
        requested = datetime.fromisoformat(sample["requested_at_utc"])
        actual_timing = timing(requested, slot)
        report.update(
            status="observed" if actual_timing == "on_time" else "late_request",
            historical_snapshot_verified=actual_timing == "on_time",
            api_calls=sample["api_calls"],
            requested_at_utc=requested.isoformat(),
            request_offset_seconds=round((requested - slot).total_seconds(), 3),
            sample_file=sample_path.name,
            sample=sample,
        )
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        # HTTP/설정 예외의 본문·URL·키를 기록하지 않는다.
        report.update(
            status="probe_failed",
            completed_at_utc=now().isoformat(),
            error="probe failed; details omitted",
            api_calls=None,
            request_count_unknown=True,
        )
    write_new(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        report = observe(args.slot, args.output, live=args.live)
    except (ValueError, OSError):
        raise SystemExit(
            "slot probe configuration/output error; details omitted"
        ) from None
    print(json.dumps(report, ensure_ascii=True))
    if report["status"] not in {"plan", "observed", "already_recorded"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
