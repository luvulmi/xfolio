# XFolio

XFolio는 미국 시장 수집→AI 생성→검토/버전 승인→정시 X 게시→장애 알림을 연결하는 풀스택 포트폴리오입니다. **2026-10-28 목표는 React·TypeScript + FastAPI + PostgreSQL + Docker + AWS**, 아침 최대 3글과 낮 감시 후 **18시 최대 2뉴스**, 중요 오류/한도의 **Telegram Bot 알림**입니다. [확정 요구사항](docs/요구사항.md) · [2주 MVP 일정](tasks/plans/개발_일정.md) · [우선순위](tasks/plans/개발_우선순위.md)

기존 Python 지수/뉴스 수집·BLS 시험·가상 미리보기·Luna 가상 분석·Neon 가상 저장과 이전 Streamlit 인증에 더해, 뉴스 선정 정책과 합성 회귀 사례·React 관리자·FastAPI 인증/조회/승인 초기 코드·운영 DB migration을 작성했습니다. 격리 PostgreSQL 통합과 로컬 HTTPS의 실제 Google 로그인·세션 유지·로그아웃을 검증했습니다. PostgreSQL 운영 배포·실뉴스 연결·X·worker·Telegram·AWS 제품 배포는 후속입니다. [초기 구현 결과](tasks/logs/2026-10-28_뉴스_선정과_관리자_초기_구현.md) · [실제 로그인 결과](tasks/logs/2026-10-29_Google_callback과_로그인_검증.md)

생성·분석 기본 모델은 **`gpt-6-luna`**입니다. CLI의 가상 `ai-preview`도 옵션 생략 시 Luna를 사용하며, 과거 `gpt-5.4-mini` 시험은 비교 기록으로 유지합니다. [모델 선택·실측](docs/research/OpenAI_활용.md)

## 기존 가상 클라우드 시험 · 2026-10-25

Neon Free PostgreSQL과 [기존 비공개 Streamlit 앱](https://xfolio-yuring.streamlit.app/)을 연결했습니다. 본인 Google 로그인·로그아웃 후 접근 차단, 가상 초안 저장·조회·중복 방지를 검증했습니다. 앱에는 가상 표 SELECT·INSERT만 가능한 역할을 사용합니다. 당시 Cloud Run Jobs·Cloud Scheduler는 결제 계정 미연결로 보류했습니다. 이 절은 새 AWS 관리자·worker의 배포 완료 기록이 아닙니다.

```powershell
uv sync --extra dashboard --extra cloud
uv run --extra cloud python -m xfolio.cloud
uv run --env-file .env --extra cloud python -m xfolio.cloud --run --initialize
```

두 번째 명령은 무통신이며 세 번째부터 실제 DB에 가상 자료를 씁니다. 접속 URL은 Git에서 제외한 `.env`의 `XFOLIO_DATABASE_URL`에 설정합니다. 값과 비밀번호를 로그·채팅에 출력하지 않습니다. 운영 수집 커서·근거·승인·게시 표의 이전과 실제 예약은 후속 구현입니다.

클라우드 관리자 진입점은 `dashboard/cloud_app.py`입니다. [배포·비밀 설정·시험 절차](deploy/cloud/README.md)와 [전환 계획](tasks/plans/클라우드_전환.md), [실행 결과](tasks/logs/2026-10-25_클라우드_전환_준비.md)를 참고하세요. Cloud 비용은 무료 한도 사용을 목표로 하며 실제 전체 청구 $0을 확정한 것은 아닙니다.

## React·FastAPI 초기 관리자

로컬 HTTPS·기존 Google 설정의 명시적 재사용은 [개발 도구](scripts/dev/README.md)를 따른다. 10/29에 로컬 callback 등록과 실제 허용 운영자의 로그인·세션·로그아웃을 확인했다. 다른 환경은 해당 HTTPS origin과 callback 등록이 필요하다. 격리 FastAPI·PostgreSQL·HTTPS의 자동 브라우저 시험은 `frontend/`의 `npm run test:integration`이며 Google 제공자만 모의한다.

Python 의존성은 `uv sync`, 프론트는 Node.js 22에서 설치합니다.

```powershell
uv sync
uv run uvicorn xfolio.api.app:app --host 127.0.0.1 --port 8000
```

별도 터미널에서 다음을 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
npm test -- --run
npm run build
```

Vite의 `/api` 요청은 로컬 `127.0.0.1:8000`으로 전달합니다. 설정이 없는 API는 503으로 차단됩니다. 로그인 성공·운영 데이터·승인 결과를 가짜로 만드는 개발 로그인 경로는 제공하지 않습니다. 실제 Google 로그인에는 같은 origin의 HTTPS 진입점과 등록된 callback이 필요합니다. 단순 HTTP 개발 서버에서는 Secure 세션 쿠키를 사용하는 전체 로그인 흐름을 완료할 수 없습니다.

`.env.example`의 `XFOLIO_API_DATABASE_URL`(API/worker 역할), `XFOLIO_PUBLIC_ORIGIN`(경로 없는 HTTPS origin), Google client ID/secret, 허용 이메일 목록(`XFOLIO_ALLOWED_EMAILS`, 쉼표 구분), `XFOLIO_API_CURSOR_SECRET`(무작위 32자 이상)을 준비합니다. `XFOLIO_MODE` 기본은 `dry_run`입니다. 비밀 파일은 자동으로 읽지 않으며 필요하면 `uv run --env-file .env uvicorn ...`처럼 명시합니다. 브라우저에는 이 환경변수들을 넣지 않습니다.

새 운영 schema는 기존 `preview_drafts`와 별도입니다. DDL 역할의 `XFOLIO_MIGRATION_DATABASE_URL`을 **별도 초기 개발 DB**에 지정한 뒤 migration을 적용합니다. API가 시작하면서 DDL을 실행하지 않습니다.

```powershell
uv run alembic upgrade head --sql
# 대상 DB·권한을 확인한 뒤 실제 migration
uv run --env-file .env alembic upgrade head
uv run python -m xfolio.api.export_openapi
```

`--sql`은 DB에 접속하지 않지만 `XFOLIO_MIGRATION_DATABASE_URL`은 필요합니다. 오프라인 검토만 할 때는 `postgresql+psycopg://offline@localhost/offline` 같은 시험용 URL을 현재 셸에 지정할 수 있습니다. 이 URL로 실제 `upgrade head`를 실행하지 않습니다.

OpenAPI 산출물은 [contracts/openapi.json](contracts/openapi.json), 동작 계약은 [관리자 화면·승인 API](tasks/verification/관리자_화면과_승인_API.md)입니다. 합성 뉴스는 `synthetic=true`·발행 불가를 유지합니다. 조회·승인 API가 X에 전송하지 않으며 worker·실기사 입력/생성·CLI 수정·실제 게시 연결은 후속입니다.

뉴스 정책 회귀 시험은 `uv run pytest tests/test_news_selection.py`로 실행합니다. 중요성/관련성/새 사실 판단은 근거를 검토한 입력을 요구하며 이 구현이 원문에서 의미를 자동 추출한 결과라고 보지 않습니다. PostgreSQL 시험에는 일회용 DB의 `XFOLIO_TEST_DATABASE_URL`을 별도로 명시합니다. 미설정 시 관련 통합 시험은 건너뛰고 메모리 시험과 구분합니다.

## 개발 환경

2026-10-24 [yfinance](docs/research/지수_데이터.md) 지수 조회를 구현하고 실제 응답을 확인했습니다. S&P 500은 `^GSPC`, Nasdaq-100은 `^NDX`로 조회하고 종가로 등락률을 계산합니다. 일반 가격 조회용 API 키는 필요하지 않습니다. 휴장·서머타임·조기 마감 판정에는 `pandas-market-calendars`의 NYSE·NASDAQ 달력을 사용합니다.

운영 설계는 [지수 수집과 게시 모드](docs/운영_정책.md)를 따릅니다. 관리자 승인은 개발·테스트 기간에 적용하고 안정화 후 자동 검증·게시로 전환할 계획입니다. 공개 게시 조건과 오전 자료 도착은 후속 검증입니다.

현재 월 **50,000원** 상한과 **Marketaux 한 곳**에서 두 지수 관련 후보를 찾는 범위를 유지합니다. 아침 08시 최대 3글, 낮 감시 후보는 18시 최대 2글로 발행하고 적격 뉴스가 없으면 생략합니다. 2주 목표는 React 2화면·FastAPI 8API·단일 AWS worker의 reviewed MVP입니다. Marketaux의 충분한 근거·Free 완주·공개/AI 권한과 실제 게시 인증은 검증 전이며, auto는 최소 5거래일·장애 시험 후 활성화합니다. [운영 정책](docs/운영_정책.md) · [새 비용 조건](docs/research/월_비용.md)

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
uv run --extra dashboard streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

로컬 개발 화면은 실행 뒤 [로컬 미리보기](http://127.0.0.1:8501)를 엽니다. 현재 화면은 가상 초안 검토/저장용이며 실제 승인·X 전송 기능이 없습니다. 로컬용 `dashboard/app.py`와 로그인 검사가 있는 클라우드용 `dashboard/cloud_app.py`를 구분합니다. 클라우드 배포에는 위 전환 절차를 사용합니다.

의존성을 설치한 뒤에는 `pwsh -NoProfile -File scripts/run_dashboard.ps1`로 같은 설정을 실행할 수 있습니다. 이 스크립트는 작업 스케줄러에 등록하지 않으며 브라우저 자동 열기·외부 바인딩도 하지 않습니다. 실제 관리자 권한 검증·승인 기능은 R11에 맞춰 별도로 연결합니다.

## 뉴스 수집과 아침 미리보기

허용 근거의 생성→기계검사→PostgreSQL 검토 대기 초안 연결은 [생성 계약](tasks/verification/허용_실자료_생성_연결.md)에 둔다. `uv run python scripts/experiments/bls_workflow_probe.py`는 기본 무통신 계획이며, `--fetch`와 명시적 loopback 시험 DB를 주면 BLS 실자료 1GET→모의 생성→격리 schema 저장/정리를 시험한다. 유료 AI는 호출하지 않는다. 실제 모델 어댑터는 용도별 권한·가격·입출력 토큰 한도·현재 월 예산 확인이 준비된 호출자만 사용할 수 있다.

```powershell
uv run xfolio preview
uv run xfolio preview --scenario zero
uv run xfolio preview --scenario partial
uv run xfolio preview --save
```

모든 `preview`는 실제 시세·뉴스·OpenAI 호출 없이 날짜가 고정된 가상 자료를 씁니다. `news`는2글, `zero`는정상 수집 범위의 선정 뉴스0건을 표시한1글, `partial`은전체 보류·종료1입니다. 기본 실행은 저장하지 않으며 `--save`일 때만 Git에서 제외한 `data/xfolio.sqlite3`에 저장합니다. 동일 입력·문안·시각의 재실행은 중복 저장하지 않습니다. `--json`으로 입력 버전·근거·보류 이유를 볼 수 있습니다.

뉴스 앱 수집기는 다음처럼 기본 무통신 계획을 확인합니다.

```powershell
uv run xfolio news-check --start 2026-10-22T22:29:00Z --end 2026-10-23T22:30:00Z
```

실제로 조회하려면 키를 설정하고 `uv run --env-file .env xfolio news-check ... --run`을 사용합니다. `...` 대신 위 날짜 옵션을 그대로 넣거나 시간대가 있는 최근7일 안 구간으로 바꿉니다. 기본최대12GET·질의최대5페이지·요청최소3초 간격·재시도0입니다. 실제 기사 텍스트는 메모리에서만 사용하고 CLI는 최소 메타데이터만 출력합니다. 부분/실패는종료1·커서전진불가이며, 이 명령은 AI·SQLite·X 게시로 실기사를 넘기지 않습니다.

좁힌 질의도 현재 표본의 요약 근거를 충분히 확보하지 못했습니다. 실제 운영용 선정 기준·입력 범위·이용 조건을 통과한 제공처라고 표시하지 않습니다. [실제 결과와 구현 계약](tasks/verification/뉴스_수집과_아침_미리보기.md)

## 자동화 실행 방식

현재 운영 목표는 **AWS Lightsail의 Docker Compose에서 별도 Python worker 한 개가 고정 워크플로를 실행**하는 구성입니다. 뉴스 수집 → 규칙 필터 → 제한된 AI 선정/요약 → 원자료·시각·중복·길이·한도 검사 → 모드별 게시 판단 → 결과 저장 순서입니다. AI가 예약·예산·승인을 변경하거나 직접 임의 행동을 결정하지 않습니다. 기존 OpenAI SDK를 쓰며 별도 에이전트 프레임워크는 추가하지 않습니다. Cloud Scheduler/Cloud Run과 Windows 작업 스케줄러는 이전 검토·시험 이력이며 새 worker는 아직 연결 전입니다.

제품 시간표는 아침 07:00 준비·07:30 기준·08:00 목표·09:00 마감, 낮 09:00~17:00 매시간+17:30 최종 확인·17:45 동결·18:00 발행·18:10 전송 마감입니다. 개발은 dry_run→reviewed, 연속5거래일과 장애/중복 검증 뒤 auto입니다. 현재 새 worker·게시·Telegram은 미구현입니다. [운영 정책](docs/운영_정책.md) · [구현 계약](tasks/verification/2주_MVP_구현_계약.md)

## 뉴스·한국어 요약 사전 시험

아래 실험은 기본 실행에서 외부 API를 호출하지 않습니다. Marketaux는 4개 질의 계획을 보여 주며 한국어 요약은 직접 만든 가상 자료6건과 기대 판정을 보여 줍니다.

```powershell
uv run python scripts/experiments/marketaux_sample_probe.py
uv run python scripts/experiments/news_summary_probe.py
uv run xfolio ai-preview
uv run python -m scripts.experiments.compare_openai_models
uv run python -m scripts.experiments.official_macro_compare
uv run python scripts/experiments/news_event_compare.py
uv run python scripts/experiments/news_event_compare.py --official
```

현재 실행 터미널의 환경변수에 `MARKETAUX_API_TOKEN`·`OPENAI_API_KEY`를 설정하고 `--run`을 붙이면 실제 시험을 수행합니다. `.env`에 등록했다면 uv의 `--env-file` 옵션으로 읽을 수 있습니다. 스크립트 자체는 `.env`를 자동으로 읽지 않습니다.

MarketNewsAPI의 초기 관찰 기업(NVDA·AAPL·MSFT) 보도자료/일반 기사 표본은 다음 명령으로 확인합니다. 기본 실행은 무통신이고 `--run`에서만 **최대 6회 GET**을 수행합니다. `.env`의 `MARKETNEWSAPI_KEY`를 사용하며 기사 본문·요약·snippet·키는 결과에 저장하지 않습니다. 첫 페이지만 확인하므로 이 출력은 전체 수집이나 공개 게시 승인 근거가 아닙니다.

```powershell
uv run --env-file .env python scripts/experiments/marketnewsapi_sample_probe.py
uv run --env-file .env python scripts/experiments/marketnewsapi_sample_probe.py --run --limit 3 --days 90 --output tasks/verification/assets/marketnewsapi_sample_20261025.json
```

```powershell
uv run --env-file .env python scripts/experiments/marketaux_sample_probe.py --run --days 2 --pages 1
uv run --env-file .env python scripts/experiments/news_summary_probe.py --run
```

키를 채팅·코드·문서·Git에 기록하지 마세요. Marketaux는 기본4회·최대8회 GET과 최소 메타데이터 출력, OpenAI는 가상 자료만 최대6회 호출하고 실제 usage를 기록합니다. API/통신 오류가 발생하면 첫 실패에서 모델 배치를 중단하고 미실행 건수를 표시합니다. OpenAI 실행은 토큰 요금이 발생하며 키 발급 외에 해당 API 프로젝트의 사용 가능한 잔액·할당량이 필요합니다. Marketaux 실제 기사의 AI 전달·공개 게시 권한은 별도 확인합니다.

`ai-preview --run`은 **직접 작성한 가상 뉴스 1건**에만 공통 OpenAI 분석 함수를 적용해 2개 글의 검토용 초안을 만듭니다. 기본 모델은 Luna이며 `--model gpt-5.4-mini`는 과거 비교를 재현할 때만 명시합니다. `--run` 없이 실행하면 무통신 계획만 표시합니다. 같은 6건의 모델 비교 스크립트는 `--run`에서 최대 12회 OpenAI를 호출하고, 공식 거시 비교 스크립트는 BLS 원문 HTTP GET과 BLS 도메인 Web search 1회 응답을 시험합니다. 실행 결과와 비용 판단은 [공통 분석·제공처 비교](tasks/verification/OpenAI_분석과_제공처_비교.md)에 기록했습니다. 실제 기사 분석·X 게시와 연결되지 않습니다.

`news_event_compare.py`는 고정된10/18~10/24 창의 알려진 사건 비교입니다. 기본무통신, `--run`에서만 Marketaux11검색을 최소3초 간격으로 수행합니다. `--official --run`은 키 없이 공식12주소의GET 접근성만 확인하고 본문 파싱은 하지 않습니다. 고정 창이 실행일의최근7일 밖이면 Marketaux 재실행을 거부하므로 새 평가에는 사건 목록과 창을 함께 갱신해야 합니다. [결정표·실제 표본·제약](tasks/verification/뉴스_기술_결정과_동일_사건_비교.md)

API 시험 실패·키 없음과 정상0건, 모의 usage와 실측을 구분합니다. [표본 평가·판정 기준](tasks/verification/뉴스_샘플과_요약_시험.md) · [작업 결과](tasks/logs/2026-10-24_뉴스_샘플_검토.md)

SEC의 과거 실적 공시에서 직접 대조한 사실 카드 3건의 별도 미리보기 실험은 아래처럼 기본 무통신으로 실행합니다. `--run`에서만 OpenAI에 최대 3회 요청하며 초안과 사용량을 지정 파일에 저장합니다. 회사 공시 전문을 모델에 보내지 않고 X에도 게시하지 않습니다. 이 실험은 현재 CLI·관리자 승인 파이프라인과 연결되어 있지 않습니다. [검증 결과](tasks/verification/SEC_기업_공시_발견과_요약_시험.md)

```powershell
uv run python scripts/experiments/sec_fact_card_preview.py
uv run --env-file .env python scripts/experiments/sec_fact_card_preview.py --run --output tasks/verification/assets/sec_fact_card_preview_20261025.json
```

2026-10-24 실제 시험 후 Marketaux를 단일 뉴스 어댑터 개발 대상으로 정했습니다. 다만 넓은24시간 거시 검색은138페이지 추산으로 무료100회/일을 넘었으며, 근거 충분성·이용 범위 확인 뒤 공개 운영을 판단합니다. Mini 가상6건·교정2건의 실제 usage 합계는 $0.00677325입니다. 실험 성공과 뉴스·AI 앱 구현을 구분합니다.

증분 실험은 아래처럼 기본 무통신으로 계획을 확인합니다. `--run`에서만 요청하며 실제 서비스 커서는 쓰지 않습니다. 과거 평일 재생은 당시 예약 실행을 재현한 것이 아니라 고정 발행 시각 창을 현재 API에서 검색하는 시험입니다.

```powershell
uv run python scripts/experiments/marketaux_incremental_probe.py --repeat
uv run python scripts/experiments/marketaux_incremental_probe.py --replay-date 2026-10-23
```

재생 날짜는 실행일의 최근6일 안 평일로 바꿉니다. 일일 사용량을 확인한 뒤 실제 호출 여부를 정하고,402·429·통신 오류 또는 부분 수집을 정상0건으로 처리하지 않습니다.

## 두 지수 종가 조회

```powershell
uv run xfolio market-close
uv run xfolio market-close --json
```

기본 출력은 두 지수의 완료 거래일 종가·등락률·출처·수집 시각입니다. `--json`은 원본 종가 정밀도, 직전 종가, 미국 거래일, 달력상 마감 시각과 실제 수집 UTC 시각을 포함합니다. JSON의 소수는 문자열로 보존합니다. 종가 화면 표시는 소수 둘째 자리 `HALF_UP` 반올림입니다.

기대한 거래일의 종가가 없거나 한 지수라도 실패하면 종료 코드1과 오류를 표시하고 전체 결과를 보류합니다. 낡은 데이터로 대체하지 않습니다. 조회만 수행하며 X에 게시하거나 예약 작업을 등록하지 않습니다. 상세 계약·검증 범위는 [종가 조회 검증](tasks/verification/지수_종가_조회.md), 오전 도착 시험은 [검증 계획·기록](tasks/verification/지수_오전_도착.md)을 참고하세요.

## BLS 공식 근거와 뉴스 수집 기록

```powershell
uv run xfolio bls-check
uv run xfolio bls-check --run --save
uv run python scripts/experiments/provider_observation.py
```

`bls-check` 기본은 무통신 계획이며 `--run`은 BLS CPI 설명문·일정 2GET을 수행합니다. `--save`는 BLS 허용 설명문과 근거 버전을 로컬 SQLite에 보관합니다. 표/PDF는 파싱하지 않으며 최신 CPI 조회를 과거 창 전체 수집으로 취급하지 않습니다. 실제 게시나 OpenAI 호출은 없습니다.

기존 `news-check --start ... --end ... --run`에 `--save-run`을 추가하면 본문 없이 수집 기록과 완료 커서를 저장합니다. `--db`로 로컬 시험 DB를 지정할 수 있습니다. 모든 필수 질의 완료 때만 커서가 전진하며 부분/실패·공백·동시 실행 충돌은 별도 기록됩니다. 아직 다음 조회 창을 자동 생성하지 않습니다. 이 뉴스 저장소는 로컬 SQLite이며 클라우드 preview 저장소와 별도입니다.

`provider_observation.py --run`은 환경변수 또는 로컬 `.env`의 `MARKETAUX_API_TOKEN`을 읽어 제한된 시장/업종 표본을 기록합니다. 회당 최대 6API 요청, 일별 최대 2슬롯입니다. API 본문은 파일에 보관하지 않습니다. 상세 범위·채택 조건은 [BLS 및 제공처 검증](tasks/verification/BLS_파서와_제공처_채택.md)을 따릅니다.

## 환경 변수 설정

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

Windows 샌드박스에서 임시 폴더 권한 오류가 나면 `.venv/pytest_tmp`를 만든 뒤 `PYTEST_DEBUG_TEMPROOT`를 그 절대 경로로 지정해 재실행합니다. 뉴스 시험은 MockTransport·가상 시계를 사용하며 실제 API나 실제 대기를 요구하지 않습니다.

## Codex 작업 권한

`.codex/config.toml`은 저장소 내부 작업에 `workspace-write`를 사용하고, 샌드박스 경계를 넘는 승인 요청은 가능한 경우 `auto_review`로 보냅니다. 프로젝트 설정은 저장소를 신뢰한 뒤 새 Codex 세션에서 적용됩니다. ChatGPT 데스크톱 앱에서는 설정에서 Auto-review를 활성화해야 사용할 수 있습니다. 실제 X 게시에는 별도로 사용자의 명시적 요청 또는 승인이 필요합니다.

## 문서와 작업 기록

- [프로젝트 문서](docs/README.md): 개요·요구사항·기술·운영 기준과 조사 근거
- [작업 문서](tasks/README.md): 계획·검증·기록·발표·논의
- [3주차 발표 자료](tasks/presentations/3주차_기술_조사.md): 기술 선택과 예상 비용
