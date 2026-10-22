# Repository instructions

- 모든 응답과 진행 상황 설명은 한국어로 작성하세요. 코드, 명령어, 파일명, 고유 명사는 원문을 유지하세요.

## 작업 완료 응답

- 사용자가 요청한 작업이나 명령 수행을 마치면 결과와 검증 내용을 보고하고, 최종 응답의 마지막에 현재 상태에서 이어갈 다음 작업 1~3개를 우선순위대로 간결하게 추천하세요.

## 프로젝트 구조

- XFolio는 시장·뉴스 수집 → AI 분석·콘텐츠 생성 → X 게시를 목표로 하는 Python 3.12·`uv` 프로젝트입니다.
- `docs/overview.md`는 목표와 범위, `docs/weekly_schedule.md`는 스터디 일정, `docs/project_structure_and_tech_stack.md`는 현재 기술 선택의 기준입니다. 설계 초안과 미결정 사항을 확정 요구사항처럼 다루지 마세요.
- `pyproject.toml`·`uv.lock`은 루트, 애플리케이션 코드는 `src/xfolio/`, 테스트는 `tests/`, 대시보드는 `dashboard/`에 둡니다.

## 테스트 명령

- 환경 설치: `uv sync`; CLI 확인: `uv run xfolio status`.
- 정적 검사: `uv run ruff check .`와 `uv run ruff format --check .`.
- 기능 테스트를 추가한 뒤 `uv run pytest`를 실행하세요. 현재는 테스트 파일이 없습니다.
- 변경 후 관련 검증을 실제로 실행하고 결과를 보고하세요.
- PowerShell에서 Python으로 한국어 스크립트를 파이프할 때는 인코딩에 의존하지 않도록 파일 기반 스크립트나 ASCII 검사식을 사용하세요. 검증 명령을 연속 실행하면 각 명령의 종료 코드를 확인하세요.
- Markdown은 BOM 없는 UTF-8로 저장하세요. 기존 파일에 BOM이 있으면 첫 줄 패치 전에 확인하고 UTF-8로 읽어 수정하세요.

## 코드 규칙

- 사용자가 저장소 수정을 요청하면 관련 파일의 읽기·수정과 필요한 검증을 추가 확인 없이 바로 진행하세요. 도구가 실제 승인을 요구하는 경우에만 해당 승인 절차를 따르세요.
- 새 의존성과 실행·설정 방법은 `pyproject.toml`과 `README.md`에 반영하고, 비밀 키·토큰·`.env`는 Git에 넣지 마세요.
- 파이프라인 간 데이터에는 출처와 기준·발행 시점을 남기세요. 기준일·시간대, 오류 처리, 중복 게시 방식을 구현 전에 문서화하세요.
- X 게시 전 미리보기 또는 시험 실행과 성공·실패 확인을 마련하세요. 실제 외부 게시에는 사용자의 명시적 요청 또는 승인이 필요합니다.

## 디렉토리별 주의사항

- `docs/`: 프로젝트 요구사항과 설계 결정을 기록합니다. 파일명은 영어 `snake_case`로 작성합니다(`README.md` 제외). 주차별 일정은 현재 요청보다 우선하지 않습니다.
- `docs/research/`: 데이터 제공처, 이용 조건, 참고 서비스 등 조사 관련 문서를 모읍니다. 앞으로 새 research 문서는 `docs/` 루트가 아닌 이 폴더에 생성하고, 이동 시 참조 링크도 함께 갱신하세요.
- `tasks/`: 주제별 작업 계획은 루트에, 날짜별 진행 기록은 `progress/YYYY-MM-DD.md`에 둡니다. 폴더명과 파일명은 영어 `snake_case`로 작성합니다(`README.md`와 ISO 형식의 날짜 파일명 제외). `tasks/README.md`에 작업 문서 링크를 유지합니다. GitHub Issues를 쓰면 업무 목록을 중복 관리하지 마세요.
- `src/xfolio/`: `Market Pipeline`, `News Pipeline`, 분석·생성, `Upload Pipeline`의 입출력 경계를 분명히 하세요. 지수 수집은 `yfinance`의 `^GSPC`·`^NDX`를 사용하기로 확정했습니다. 뉴스 제공처는 미정이며 실행·배포는 현재 기술 스택 문서의 Windows 로컬 구성을 따릅니다. 기술 선택을 실제 연동 완료로 취급하지 마세요.
- `dashboard/`: 선택 의존성 `streamlit`을 사용합니다. 실행 명령은 `uv run --extra dashboard streamlit run dashboard/app.py`입니다.
- `tests/`: 기능을 구현할 때 외부 API에 의존하지 않는 검증을 추가하세요.

## 커밋 메시지

- Git 커밋은 사용자가 명시적으로 요청한 경우에만 수행하세요.
- `git commit`과 `git push`를 승인 없이 실행하는 `allow` 규칙은 추가하지 마세요.
- 커밋 메시지의 제목과 본문은 한국어로 작성하세요. Conventional Commits 타입 접두사(`feat:`, `fix:`, `docs:` 등)는 영어를 허용합니다.
- 예: `docs: XFolio 주차별 개발 일정 정리`.
