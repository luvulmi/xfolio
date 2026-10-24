"""XFolio 명령행 진입점."""

import argparse
from collections.abc import Sequence

from xfolio.market import MarketDataError, collect_index_closes, display_number


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="XFolio 개발용 명령")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="현재 구현 상태 확인")
    market = commands.add_parser("market-close", help="두 지수의 완료 거래일 종가 조회")
    market.add_argument(
        "--json", action="store_true", help="공통 출력 모델을 JSON으로 표시"
    )
    args = parser.parse_args(argv)

    if args.command == "status":
        print("지수 종가 조회: 구현됨 (market-close). 뉴스·AI·X 게시: 구현 전.")
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
