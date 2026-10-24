# XFolio

XFolio는 현재의 시장 정보와 뉴스를 수집·분석해 X 게시용 브리핑을 만드는 개인 AI 에이전트 프로젝트입니다. 현재는 yfinance로 두 지수의 완료 거래일 종가를 조회하는 CLI를 구현했습니다. 클라우드 배포용 가상 미리보기·PostgreSQL 저장과 운영자 인증 진입점을 추가했습니다. 실뉴스 수집·AI 분석·승인·X 게시는 이 커밋에 포함하지 않습니다.

## 클라우드 전환 · 2026-10-25

Neon Free PostgreSQL·비공개 Streamlit Community Cloud·Cloud Run Jobs·Cloud Scheduler를 전환 목표로 선택했습니다. 현재 Neon 가상 초안 저장·조회·중복 방지와 SQLite 가상 자료 복사·재실행을 실제 확인했습니다. 관리자 Google OIDC 진입점과 컨테이너는 준비 단계이며 실제 사이트·job·예약·운영 백업은 배포 전입니다. 아래 Windows 로컬 실행은 개발용으로 유지합니다.

```powershell
uv sync --extra dashboard --extra cloud
uv run --extra cloud python -m xfolio.cloud
uv run --env-file .env --extra cloud python -m xfolio.cloud --run --initialize
```

두 번째 명령은 무통신이며 세 번째부터 실제 DB에 가상 자료를 씁니다. 접속 URL은 Git에서 제외한 `.env`의 `XFOLIO_DATABASE_URL`에 설정합니다. 값과 비밀번호를 로그·채팅에 출력하지 않습니다. 운영 수집 커서·근거·승인·게시 표의 이전과 실제 예약은 후속 구현입니다.

클라우드 관리자 진입점은 `dashboard/cloud_app.py`입니다. [배포·비밀 설정·시험 절차](deploy/cloud/README.md)와 [전환 계획](tasks/plans/클라우드_전환.md), [실행 결과](tasks/logs/2026-10-25_클라우드_전환_준비.md)를 참고하세요. Cloud 비용은 무료 한도 사용을 목표로 하며 실제 전체 청구 $0을 확정한 것은 아닙니다.

## 개발 환경

2026-10-24 [yfinance](docs/research/지수_데이터.md) 지수 조회를 구현하고 실제 응답을 확인했습니다. S&P 500은 `^GSPC`, Nasdaq-100은 `^NDX`로 조회하고 종가로 등락률을 계산합니다. 일반 가격 조회용 API 키는 필요하지 않습니다. 휴장·서머타임·조기 마감 판정에는 `pandas-market-calendars`의 NYSE·NASDAQ 달력을 사용합니다.

운영 설계는 [지수 수집과 게시 모드](docs/운영_정책.md)를 따릅니다. 관리자 승인은 개발·테스트 기간에 적용하고 안정화 후 자동 검증·게시로 전환할 계획입니다. 공개 게시 조건과 오전 자료 도착은 후속 검증입니다.

실행·저장·관리자는 위 클라우드 전환을 목표로 하며 기존 Windows 로컬 실행은 개발용으로 유지합니다. 아침 출처 링크는 한 글로 모으고 기업 뉴스는 하루 최대 1회·1개 글입니다. 승인·예약 게시 기능과 클라우드 예약 등록은 구현 전입니다.

- Python 3.12
- `uv`로 의존성 설치 및 명령 실행

저장소 루트에서 다음 명령을 실행합니다.

```powershell
uv sync
uv run xfolio status
```

`uv.lock`에 기록된 버전으로 환경을 설치합니다. 로컬 가상 미리보기를 실행하려면 선택 의존성을 설치합니다.

```powershell
uv sync --extra dashboard
uv run --extra dashboard streamlit run dashboard/app.py
```

## 두 지수 종가 조회

```powershell
uv run xfolio market-close
uv run xfolio market-close --json
```

기본 출력은 두 지수의 완료 거래일 종가·등락률·출처·수집 시각입니다. `--json`은 원본 종가 정밀도, 직전 종가, 미국 거래일, 달력상 마감 시각과 실제 수집 UTC 시각을 포함합니다. JSON의 소수는 문자열로 보존합니다. 종가 화면 표시는 소수 둘째 자리 `HALF_UP` 반올림입니다.

기대한 거래일의 종가가 없거나 한 지수라도 실패하면 종료 코드1과 오류를 표시하고 전체 결과를 보류합니다. 낡은 데이터로 대체하지 않습니다. 조회만 수행하며 X에 게시하거나 예약 작업을 등록하지 않습니다. 상세 계약·검증 범위는 [종가 조회 검증](tasks/verification/지수_종가_조회.md), 오전 도착 시험은 [검증 계획·기록](tasks/verification/지수_오전_도착.md)을 참고하세요.

## 환경 변수

지수 조회에는 `.env`나 API 키가 필요하지 않습니다. `.env.example`은 향후 OpenAI 설정의 예시이며 실제 키는 `.env` 또는 실행 환경에 두고 Git에 추가하지 마세요. X 인증 방식과 설정값은 게시 기능을 구현할 때 확정합니다.

## 검증

현재 구현된 CLI와 코드 형식을 아래 명령으로 확인합니다.

```powershell
uv run xfolio status
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

단위 테스트는 Yahoo 요청을 차단하고 합성 응답으로 날짜·종가·등락률·실패 시 보류를 확인합니다. `market-close` 실제 실행에는 인터넷이 필요합니다.

## Codex 작업 권한

`.codex/config.toml`은 저장소 내부 작업에 `workspace-write`를 사용하고, 샌드박스 경계를 넘는 승인 요청은 가능한 경우 `auto_review`로 보냅니다. 프로젝트 설정은 저장소를 신뢰한 뒤 새 Codex 세션에서 적용됩니다. ChatGPT 데스크톱 앱에서는 설정에서 Auto-review를 활성화해야 사용할 수 있습니다. 실제 X 게시에는 별도로 사용자의 명시적 요청 또는 승인이 필요합니다.

## 문서와 작업 기록

- [프로젝트 문서](docs/README.md): 개요·요구사항·기술·운영 기준과 조사 근거
- [작업 문서](tasks/README.md): 계획·검증·기록·발표·논의
- [3주차 발표 자료](tasks/presentations/3주차_기술_조사.md): 기술 선택과 예상 비용
