# Python 테스트

`uv run pytest`로 전체를 실행한다. 시험은 기능별 폴더에서 찾고, 정적 자료는 `fixtures/`, 공용 보조 코드는 `support/`에 둔다. 외부 공급자·유료 AI·실제 Telegram 송신은 시험 대역을 사용한다.

| 폴더 | 검증 범위 |
| --- | --- |
| `api/` | Google 세션·OIDC·CSRF·revision/멱등·관리자 API·DB 비용/시세 신선도·뉴스/준비/송신 상태 |
| `market/` | 국내 KIS/거래일·종목/가격90일 DB와 기존 미국 ETF/지수의 종가·수정치·달력 |
| `news/` | Finnhub/BLS/BEA/Board·중요도·기발송·24/96h·공통 입력/권리·Exa·사건 선정 |
| `ai/` | 생성 SDK·단가/예산·토큰 상한·근거/수치/기간/문형·실패/응답불명 |
| `newsletter/` | 아침 편성·최대10종목/3뉴스·휴장·07:50/08:00/08:10·불변 저장·설정 감사 |
| `jobs/` | 실제 수집 경계의 대역 연결·설정 고정·단일 claim·분할/outbox·중복/429/부분/불명·만료 |
| `integration/` | 관리자 설정→수집/요약→편성→전송→이력·삭제/복원 gate의 격리 DB 연결 |
| `deploy/` | T08 유지보수의 만료/복원·명시 실행·비밀 비노출 |
| `dev/` | 로컬 HTTPS/실행 helper·날짜 제한·Telegram 설정 도구 |
| `experiments/` | 조사/표본 도구의 무통신 동작·요청/출력 상한 |
| `legacy/` | 기존 X AM/PM·승인/검토·미리보기·가상 분석·Streamlit/클라우드 |
| `support/` | `paths.py` 저장소/fixture 공용 경로, AM/과거 PM fixture, `browser_api_server.py` 격리 HTTPS/API 서버 |
| `fixtures/` | 합성 BLS HTML·뉴스 선정 사례·생성 결과 JSON. 실사용 입력으로 주입하지 않음 |

```powershell
uv run pytest tests/news
uv run pytest tests/jobs tests/integration
uv run ruff check .
uv run ruff format --check .
uv run xfolio status
```

PostgreSQL 시험에는 `XFOLIO_TEST_DATABASE_URL`을 명시한다. 운영 `.env`·기본 DB URL은 자동 사용하지 않으며 시험마다 격리 schema를 생성/정리한다. 설정이 없으면 해당 시험을 skip한다. Windows 임시 디렉터리 제약이 있으면 `--basetemp .cache/pytest-작업명`을 지정한다.

예전 `tests/test_news_importance.py`는 `tests/news/test_news_importance.py`로 이동했다. 공용 보조/시험 간 재사용 import는 `tests.news...`, `tests.support...`처럼 패키지 경로로 작성한다. 시험 파일 자신의 깊이로 저장소 경로를 계산하지 말고 `tests.support.paths.ROOT`·`FIXTURES`를 사용한다.

프론트 검증은 `frontend/`에서 `npm test`, `npm run build`, `npm run test:e2e`다. `npm run test:integration`·`npm run test:newsletter`는 `XFOLIO_BROWSER_TEST_DATABASE_URL`의 명시적 loopback 시험 DB와 HTTPS/API를 연결한다. [프론트 안내](../frontend/README.md)

`uv run python -m xfolio.api.export_openapi`로 API 계약을 생성하고 `contracts/openapi.json`과 대조한다. 격리 시험 성공은 실제 Google 로그인·유료 생성·정시 수신·AWS 운영 인수를 대신하지 않는다.
