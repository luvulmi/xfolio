"""시험 파일 위치와 무관한 저장소·합성 자료 경로."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
