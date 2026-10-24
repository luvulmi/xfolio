# XFolio

XFolio는 현재의 시장 정보와 뉴스를 수집·분석해 X 게시용 브리핑을 만드는 개인 AI 에이전트 프로젝트입니다. 현재는 yfinance로 두 지수의 완료 거래일 종가를 조회하는 CLI를 구현했습니다. 뉴스 수집·AI 분석·X 게시는 아직 구현 전입니다.

## 개발 환경

2026-10-24 [yfinance](docs/research/지수_데이터.md) 지수 조회를 구현하고 실제 응답을 확인했습니다. S&P 500은 `^GSPC`, Nasdaq-100은 `^NDX`로 조회하고 종가로 등락률을 계산합니다. 일반 가격 조회용 API 키는 필요하지 않습니다. 휴장·서머타임·조기 마감 판정에는 `pandas-market-calendars`의 NYSE·NASDAQ 달력을 사용합니다.

운영 설계는 [지수 수집과 게시 모드](docs/운영_정책.md)를 따릅니다. 관리자 승인은 개발·테스트 기간에 적용하고 안정화 후 자동 검증·게시로 전환할 계획입니다. 공개 게시 조건과 오전 자료 도착은 후속 검증입니다.

초기 운영은 [비용 절감 구성](docs/research/월_비용.md)에 따라 기존 Windows PC·SQLite·로컬 Streamlit·Windows 작업 스케줄러를 사용하도록 정했습니다. 아침 출처 링크는 한 글로 모으고 기업 뉴스는 하루 최대 1회·1개 글입니다. 승인·예약 게시 기능과 Windows 작업 등록은 구현 전입니다.

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
