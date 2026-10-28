"""XFolio 명령행 진입점."""

import argparse
import json
import os
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from openai import OpenAI

from xfolio.analysis import DEFAULT_MODEL, MODEL_PRICES, analyze_synthetic
from xfolio.bls import BLSError, inspect_bls
from xfolio.compose import NewsSelection, build_morning_preview
from xfolio.demo import DEMO_CUTOFF, DEMO_PREPARED, demo_inputs, demo_preview
from xfolio.market import MarketDataError, collect_index_closes, display_number
from xfolio.news import collect_news, metadata_report
from xfolio.news_contracts import CollectionRun, digest
from xfolio.news_queries import FOCUSED_QUERIES
from xfolio.news_store import NewsStore
from xfolio.storage import DEFAULT_DB, StorageError, configured_store


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="XFolio 개발용 명령")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="현재 구현 상태 확인")
    market = commands.add_parser("market-close", help="두 지수의 완료 거래일 종가 조회")
    market.add_argument(
        "--json", action="store_true", help="공통 출력 모델을 JSON으로 표시"
    )
    news = commands.add_parser(
        "news-check", help="좁힌 뉴스 질의 계획 또는 실제 메타데이터 조회"
    )
    news.add_argument("--start", type=datetime.fromisoformat, required=True)
    news.add_argument("--end", type=datetime.fromisoformat, required=True)
    news.add_argument("--run", action="store_true", help="실제 Marketaux GET 수행")
    news.add_argument("--max-requests", type=int, choices=range(1, 13), default=12)
    news.add_argument("--max-pages", type=int, choices=range(1, 6), default=5)
    news.add_argument(
        "--save-run", action="store_true", help="메타데이터와 완료 커서를 SQLite에 기록"
    )
    news.add_argument("--db", type=Path, default=DEFAULT_DB)
    bls = commands.add_parser("bls-check", help="BLS CPI 본문·일정 진단. 기본 무통신")
    bls.add_argument("--run", action="store_true")
    bls.add_argument(
        "--save", action="store_true", help="허용된 BLS 설명문·근거를 SQLite에 저장"
    )
    bls.add_argument("--db", type=Path, default=DEFAULT_DB)
    preview = commands.add_parser("preview", help="가상 자료로 아침 게시글 미리보기")
    preview.add_argument(
        "--scenario", choices=("news", "zero", "partial"), default="news"
    )
    preview.add_argument("--json", action="store_true")
    preview.add_argument(
        "--save", action="store_true", help="가상 결과를 설정된 저장소에 저장"
    )
    preview.add_argument("--db", type=Path, help="로컬 SQLite 경로를 명시적으로 선택")
    ai = commands.add_parser("ai-preview", help="가상 뉴스의 AI 분석·미리보기 시험")
    ai.add_argument("--run", action="store_true", help="가상 자료만 OpenAI에 전송")
    ai.add_argument("--model", choices=tuple(MODEL_PRICES), default=DEFAULT_MODEL)
    args = parser.parse_args(argv)

    if args.command == "status":
        print(
            "지수·뉴스 수집·BLS CPI 파서·수집 커서·가상 미리보기: 구현됨. "
            "뉴스 선정 정책·관리자 API/React·DB migration: 초기 구현. "
            "실기사 AI·운영 승인 검증·X/worker·Telegram·AWS 배포: 연결 전."
        )
    elif args.command == "bls-check":
        if not args.run:
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "network_requests": 0,
                        "planned_requests": 2,
                        "scope": "BLS CPI narrative and schedule",
                        "can_publish": False,
                    }
                )
            )
            return
        try:
            with httpx.Client() as client:
                bundle, report = inspect_bls(client=client, run_id=str(uuid4()))
            if args.save:
                report["storage_result"] = NewsStore(args.db).save_evidence(bundle)
        except (BLSError, ValueError, sqlite3.Error, OSError):
            parser.exit(1, "BLS 파싱·저장 실패: 응답/본문 구조·시각·DB를 확인하세요.\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["state"] != "snapshot_parsed":
            parser.exit(1, "예정 발표가 아직 확인되지 않아 보류합니다.\n")
    elif args.command == "market-close":
        try:
            snapshot = collect_index_closes()
        except MarketDataError as exc:
            parser.exit(1, f"시장 데이터 조회 실패: {exc}\n")
        if args.json:
            print(snapshot.model_dump_json(indent=2))
        else:
            print(f"기준 거래일: {snapshot.trade_date} (미국 현지 날짜)")
            for index in snapshot.indices:
                change = display_number(index.change_pct)
                if index.change_pct > 0:
                    change = f"+{change}"
                print(
                    f"{index.name} ({index.symbol}): "
                    f"{display_number(index.close)} / {change}%"
                )
                print(f"  출처: {index.provider} | {index.source_url}")
                print(f"  수집 시각: {index.retrieved_at.isoformat()}")
    elif args.command == "news-check":
        if not args.run:
            from dataclasses import asdict

            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "network_requests": 0,
                        "start": args.start.isoformat(),
                        "end": args.end.isoformat(),
                        "queries": [asdict(query) for query in FOCUSED_QUERIES],
                        "max_requests": args.max_requests,
                        "max_pages": args.max_pages,
                        "notice": "질의 계획만 표시합니다. 실제 요청은 --run이 필요합니다.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        store, cursor_before = None, None
        from dataclasses import asdict

        query_version = digest(
            json.dumps([asdict(q) for q in FOCUSED_QUERIES], sort_keys=True)
        )
        if args.save_run:
            try:
                store = NewsStore(args.db)
                cursor_before = store.cursor("Marketaux", query_version, "focused")
            except (sqlite3.Error, OSError):
                parser.exit(1, "수집 기록 DB를 열 수 없습니다.\n")
        try:
            result = collect_news(
                start=args.start,
                end=args.end,
                token=os.environ.get("MARKETAUX_API_TOKEN", ""),
                max_requests=args.max_requests,
                max_pages=args.max_pages,
            )
        except ValueError:
            parser.exit(
                1, "뉴스 요청 설정 오류: 키·시간대·7일 이내 조회 범위를 확인하세요.\n"
            )
        report = metadata_report(result)
        if store is not None:
            try:
                run = CollectionRun(
                    run_id=str(uuid4()),
                    provider="Marketaux",
                    query_version=query_version,
                    scope="focused",
                    window_start=result.window_start,
                    window_end=result.window_end,
                    finished_at=result.collected_at,
                    cursor_before=cursor_before,
                    required_queries=tuple(q.query_id for q in FOCUSED_QUERIES),
                    completed_queries=tuple(
                        q.query_id
                        for q in result.query_reports
                        if q.status == "complete" and q.error is None
                    ),
                    status=result.status,
                    requests=result.requests,
                    error=result.error,
                )
                report["checkpoint_result"] = store.finish(run)
            except (ValueError, sqlite3.Error, OSError):
                parser.exit(1, "수집 기록 저장 실패: 완료 커서를 확인하세요.\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if result.status != "complete":
            parser.exit(1, "뉴스 수집이 완전하지 않아 발행을 보류합니다.\n")
    elif args.command == "preview":
        result = demo_preview(args.scenario)
        saved = None
        if args.save:
            try:
                saved = configured_store(args.db).save(result)
            except (StorageError, sqlite3.Error, OSError, ValueError):
                parser.exit(
                    1, "가상 미리보기 저장 실패: DB 경로와 상태를 확인하세요.\n"
                )
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print("가상 자료 미리보기 · dry_run · 실제 게시 없음")
            print(f"상태: {result.status}")
            for position, post in enumerate(result.posts, 1):
                print(
                    f"\n글 {position} · 가중 길이 참고 {post.weighted_length_estimate}/280"
                )
                print(post.text)
            for reason in result.reasons:
                print(f"사유: {reason}")
            print(result.length_notice)
            if saved is not None:
                print(
                    "가상 초안 저장 완료"
                    if saved
                    else "같은 가상 초안이 이미 저장돼 있습니다."
                )
        if result.status == "held":
            parser.exit(1, "아침 미리보기가 보류됐습니다.\n")
    elif args.command == "ai-preview":
        if not args.run:
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "network_requests": 0,
                        "model": args.model,
                        "synthetic": True,
                        "can_publish": False,
                    },
                    ensure_ascii=False,
                )
            )
            return
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            parser.exit(2, "OPENAI_API_KEY 환경변수가 필요합니다.\n")
        market, news, _ = demo_inputs()
        article = news.articles[0]
        with OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            timeout=30,
            max_retries=0,
        ) as client:
            report = analyze_synthetic(
                client,
                source_id=article.article_id,
                source_text=article.description,
                required_literals=("2.5%",),
                model=args.model,
            )
        selection = None
        if report["status"] == "mechanical_checks_passed" and report.get("selected"):
            selection = NewsSelection(
                article_id=article.article_id,
                summary_ko=report["summary_ko"],
                evidence=report["evidence"],
            )
        if selection is None:
            print(
                json.dumps(
                    {"mode": "run", "status": "held", "analysis": report},
                    ensure_ascii=False,
                )
            )
            parser.exit(1, "AI 초안을 보류했습니다.\n")
        result = build_morning_preview(
            market=market,
            news=news,
            selection=selection,
            information_cutoff=DEMO_CUTOFF,
            prepared_at=DEMO_PREPARED,
        )
        print(
            json.dumps(
                {
                    "mode": "run",
                    "analysis": report,
                    "preview": result.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )
        if result.status != "ready" or len(result.posts) != 2:
            parser.exit(1, "AI 미리보기를 보류했습니다.\n")
