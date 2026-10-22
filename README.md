# XFolio

XFolio는 현재의 시장 정보와 뉴스를 수집·분석해 X 게시용 브리핑을 만드는 개인 AI 에이전트 프로젝트입니다. 현재는 개발 환경과 폴더 구조만 구성되어 있으며, 데이터 수집·AI 분석·X 게시 기능은 아직 구현되지 않았습니다.

## 개발 환경

2026-10-23 지수 수집 수단을 [yfinance](docs/research/week3/yfinance_index_collection.md)로 확정했습니다. S&P 500은 `^GSPC`, Nasdaq-100은 `^NDX`로 조회하고 종가로 등락률을 계산합니다. 일반 조회용 API 키는 필요하지 않습니다. 라이브러리 설치·수집 구현·실제 응답 시험은 아직 수행하지 않았습니다.

운영은 [지수 수집과 게시 모드](docs/market_search_and_publishing_modes.md)를 따릅니다. 관리자 승인은 개발·테스트 기간에 적용하고 안정화 후 자동 검증·게시로 전환합니다. 공개 게시 조건과 오전 자료 도착은 검증 과제로 남기며, 현재 코드는 골격입니다.

초기 운영은 [비용 절감 구성](docs/minimum_cost_configuration.md)에 따라 기존 Windows PC·SQLite·로컬 Streamlit·Windows 작업 스케줄러를 사용하도록 정했습니다. 아침 출처 링크는 한 글로 모으고 기업 뉴스는 하루 최대 1회·1개 글입니다. 아래 명령은 현재 골격 실행용이며 수집·승인·예약 게시 기능과 Windows 작업 등록은 구현 전입니다.

- Python 3.12
- `uv`로 의존성 설치 및 명령 실행

저장소 루트에서 다음 명령을 실행합니다.

```powershell
uv sync
uv run xfolio status
```

`uv.lock`에 기록된 버전으로 환경을 설치합니다. 대시보드 골격을 실행하려면 선택 의존성을 설치합니다.

```powershell
uv sync --extra dashboard
uv run --extra dashboard streamlit run dashboard/app.py
```

## 환경 변수

`.env.example`은 필요한 설정의 예시입니다. 실제 키는 `.env` 또는 실행 환경의 환경 변수에 설정하고 Git에 추가하지 마세요. 아직 외부 API 호출은 구현되지 않았으므로 실행에 키가 필요하지 않습니다. X 인증 방식과 설정값은 게시 기능을 설계할 때 확정합니다.

## 검증

현재 구현된 CLI와 코드 형식을 아래 명령으로 확인합니다.

```powershell
uv run xfolio status
uv run ruff check .
uv run ruff format --check .
```

`pytest`는 개발 의존성에 포함되어 있지만, 아직 테스트할 파이프라인이 없어 자동 테스트 파일은 없습니다. 기능을 추가할 때 해당 검증을 함께 추가합니다.

## Codex 작업 권한

`.codex/config.toml`은 저장소 내부 작업에 `workspace-write`를 사용하고, 샌드박스 경계를 넘는 승인 요청은 가능한 경우 `auto_review`로 보냅니다. 프로젝트 설정은 저장소를 신뢰한 뒤 새 Codex 세션에서 적용됩니다. ChatGPT 데스크톱 앱에서는 설정에서 Auto-review를 활성화해야 사용할 수 있습니다. 실제 X 게시에는 별도로 사용자의 명시적 요청 또는 승인이 필요합니다.

## 문서와 작업 기록

- `docs/overview.md`: 프로젝트 목표와 개발 범위
- `docs/weekly_schedule.md`: 스터디 일정
- `docs/project_structure_and_tech_stack.md`: 이번 구조·스택 선택과 남은 결정
- `tasks/README.md`: 주제별 작업 문서와 날짜별 진행 기록 안내
