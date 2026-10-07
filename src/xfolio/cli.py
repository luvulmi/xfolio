"""XFolio 명령행 진입점."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="XFolio 개발용 명령")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="현재 구현 상태 확인")
    args = parser.parse_args()

    if args.command == "status":
        print(
            "XFolio 개발 환경이 준비되었습니다. 파이프라인은 아직 구현되지 않았습니다."
        )
