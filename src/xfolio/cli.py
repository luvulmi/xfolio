"""XFolio 명령행 진입점."""

import argparse
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from xfolio.demo import demo_preview
from xfolio.market import MarketDataError, collect_index_closes, display_number
from xfolio.storage import StorageError, configured_store


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="XFolio 개발용 명령")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="현재 구현 상태 확인")
    market = commands.add_parser("market-close", help="두 지수의 완료 거래일 종가 조회")
    market.add_argument(
        "--json", action="store_true", help="공통 출력 모델을 JSON으로 표시"
    )
    preview = commands.add_parser("preview", help="가상 자료로 아침 게시글 미리보기")
    preview.add_argument(
        "--scenario", choices=("news", "zero", "partial"), default="news"
    )
    preview.add_argument("--json", action="store_true")
    preview.add_argument(
        "--save", action="store_true", help="가상 결과를 설정된 저장소에 저장"
    )
    preview.add_argument("--db", type=Path, help="로컬 SQLite 경로를 명시적으로 선택")
    args = parser.parse_args(argv)

    if args.command == "status":
        print("지수 종가 조회·가상 미리보기: 구현됨. 실뉴스·AI·승인·X 게시: 구현 전.")
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
