# Repository instructions

- 모든 응답과 진행 상황 설명은 한국어로 작성하세요. 코드, 명령어, 파일명, 고유 명사는 원문을 유지하세요.

## 작업 완료 응답

- 사용자가 요청한 작업이나 명령 수행을 마치면 결과와 검증 내용을 보고하고, 최종 응답의 마지막에 현재 상태에서 이어갈 다음 작업 1~3개를 우선순위대로 간결하게 추천하세요.

## 프로젝트 구조

- XFolio는 시장·뉴스 수집 → AI 분석·콘텐츠 생성 → X 게시를 목표로 하는 Python 3.12·`uv` 프로젝트입니다.
- `docs/프로젝트_개요.md`는 목적, `docs/요구사항.md`는 기능 범위, `docs/운영_정책.md`는 시각·한도·게시 정책, `docs/기술_구성.md`는 현재 기술 선택, `docs/스터디_일정.md`는 스터디 일정의 기준입니다. 설계 초안과 미결정 사항을 확정 요구사항처럼 다루지 마세요.
- `pyproject.toml`·`uv.lock`은 루트, 애플리케이션 코드는 `src/xfolio/`, 테스트는 `tests/`, 대시보드는 `dashboard/`에 둡니다.
- 2026-10-28 제품 목표는 React·TypeScript(`frontend/`) + FastAPI(`src/xfolio/api/`) + PostgreSQL + 별도 Python worker(`src/xfolio/jobs/`) + Docker/AWS입니다. 새 디렉터리·기능의 실제 구현 완료로 취급하지 마세요. `dashboard/`는 기존 Streamlit 가상 시험 자산입니다.

## 테스트 명령

- 환경 설치: `uv sync`; CLI 확인: `uv run xfolio status`.
- 정적 검사: `uv run ruff check .`와 `uv run ruff format --check .`.
- 기능 테스트를 추가한 뒤 `uv run pytest`를 실행하세요. 현재 지수 종가 수집의 외부 API 없는 테스트가 `tests/test_market.py`에 있습니다.
- 변경 후 관련 검증을 실제로 실행하고 결과를 보고하세요.
- PowerShell에서 Python으로 한국어 스크립트를 파이프할 때는 인코딩에 의존하지 않도록 파일 기반 스크립트나 ASCII 검사식을 사용하세요. 검증 명령을 연속 실행하면 각 명령의 종료 코드를 확인하세요.
- Markdown은 BOM 없는 UTF-8로 저장하세요. 기존 파일에 BOM이 있으면 첫 줄 패치 전에 확인하고 UTF-8로 읽어 수정하세요.

## 코드 규칙

- 사용자가 저장소 수정을 요청하면 관련 파일의 읽기·수정과 필요한 검증을 추가 확인 없이 바로 진행하세요. 도구가 실제 승인을 요구하는 경우에만 해당 승인 절차를 따르세요.
- 새 의존성과 실행·설정 방법은 `pyproject.toml`과 `README.md`에 반영하고, 비밀 키·토큰·`.env`는 Git에 넣지 마세요.
- 파이프라인 간 데이터에는 출처와 기준·발행 시점을 남기세요. 기준일·시간대, 오류 처리, 중복 게시 방식을 구현 전에 문서화하세요.
- X 게시 전 미리보기 또는 시험 실행과 성공·실패 확인을 마련하세요. 실제 외부 게시에는 사용자의 명시적 요청 또는 승인이 필요합니다.

## 디렉토리별 주의사항

- `docs/`: 프로젝트 요구사항과 설계 결정을 기록합니다. 문서 파일명은 한글로, 폴더명은 영어 `snake_case`로 작성합니다. 공백 대신 `_`를 사용합니다. `OpenAI`·`yfinance` 같은 고유명사는 유지합니다. 주차별 일정은 현재 요청보다 우선하지 않습니다.
- `docs/research/`: 주차별 폴더 대신 주제별로 기술·제공처·이용 조건·비용의 근거를 모읍니다. 같은 주제의 기준 문서는 하나만 두고 나머지는 링크로 연결합니다. 이전 기획·대체된 비교안은 `docs/archive/`에 현재 기준과 구별해 보존합니다.
- `tasks/`: 작업 계획은 `plans/`, 구현 계약·시험 방법·관측 근거는 `verification/`, 실제 수행 결과는 `logs/YYYY-MM-DD_주제.md`, 발표 자료·대본은 `presentations/`, 질문·결정 과정은 `discussions/`에 둡니다. 구현·검증 전용 문서를 `docs/`에 새로 만들지 마세요. 문서명은 한글과 `_`를 사용하고 `tasks/README.md`에 링크를 유지합니다. GitHub Issues를 쓰면 업무 목록을 중복 관리하지 마세요.
- `tasks/verification/`: 문서는 `market/`, `news/`, `admin/`, `ai/`, `integration/`의 해당 주제에 둡니다. 원본은 `assets/` 하위 주제 폴더에 보존하고 [목차](tasks/verification/README.md)로 연결합니다. 전체 폴더 역할은 [프로젝트 구조](docs/프로젝트_구조.md)를 따릅니다.
- `src/xfolio/`: `Market Pipeline`, `News Pipeline`, 분석·생성, `Upload Pipeline`과 API/worker의 경계를 분명히 하세요. 2026-10-30 지수 목표는 `yfinance`의 `^GSPC`·`^NDX`·`^DJI`입니다(현재 코드는 두 지수). 공식 자료 경로는 Fed·BLS·BEA와 SEC 주요 기업10개 시작20개 확장, 요약은 실적·인수합병·정책·주요 경제지표입니다. 실제 기업 명단과 세부 지원 유형은 문서의 확정/추천 구분을 따릅니다. Marketaux는 이전 실험 자산이며 기관·SEC 수집/공개 운영을 구현 완료로 취급하지 마세요. 배포는 기술 문서의 AWS Lightsail/Docker 목표, Windows는 개발용입니다. 아침과 18시 편성·Telegram 중요 알림을 운영 정책과 대조하고 선택을 실제 연동 완료로 취급하지 마세요.
- `dashboard/`: 선택 의존성 `streamlit`을 사용합니다. 실행 명령은 `uv run --extra dashboard streamlit run dashboard/app.py`입니다.
- `frontend/`: 새 React·TypeScript·Vite 관리자 계획입니다. 인증·승인·DB 검사는 FastAPI가 담당하고 브라우저에 공급자/DB/봇 비밀을 넣지 마세요. 실제 생성 시 package manifest·실행·build/검사 방법을 README에 기록하세요.
- `tests/`: 기능을 구현할 때 외부 API에 의존하지 않는 검증을 추가하세요.

## 문서 관리

- 사용자가 `tasks 작업 내용`으로 요청하거나 작업 문서 작성과 실행을 함께 요청하면 `.agents/skills/tasks/SKILL.md`를 적용하세요. 기존 작업 문서를 우선 갱신하고 문서 작성 뒤 실제 작업·검증·결과 기록을 이어 가되, 계획만 요청한 경우 그 범위를 따르세요.
- `docs/README.md`에서 요구사항·기술·운영·조사 기준 문서로 이동할 수 있게 하고, `tasks/README.md`에는 현재 작업과 발표·기록 목록을 유지하세요.
- `README.md`·`AGENTS.md`·`SKILL.md` 등 도구가 인식하는 이름과 코드 파일명은 유지하세요. 실험 코드는 `scripts/experiments/`에 둡니다.
- 최신 요구사항·정책과 이전 이력을 한 본문에 섞지 말고, 확정 사항·추천값·미결정 항목을 구분하세요.
- 이동·이름 변경 시 상대 링크·스킬의 경로·예약 자동화의 참조를 함께 갱신하고 검증하세요.

## 커밋 메시지

- Git 커밋은 사용자가 명시적으로 요청한 경우에만 수행하세요.
- `git commit`과 `git push`를 승인 없이 실행하는 `allow` 규칙은 추가하지 마세요.
- 커밋 메시지의 제목과 본문은 한국어로 작성하세요. Conventional Commits 타입 접두사(`feat:`, `fix:`, `docs:` 등)는 영어를 허용합니다.
- 예: `docs: XFolio 주차별 개발 일정 정리`.
