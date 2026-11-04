# 테스트

`uv run pytest`로 외부 API 없이 기능을 검증합니다.

`test_newsletter_news.py`는 T03 Finnhub/공식4출처·근거 요약·시각/권리·24/96h·중복·정상0건/부분/실패·일반 뉴스 AI 차단·예산/응답불명을 검사합니다. `test_newsletter_news_postgres.py`는 명시적 격리 PostgreSQL에서0004 업/다운·최초 저장/만료·confirmed만 기발송 제외·수신자 분리·본문 미보관을 검증합니다. 실제 유료 AI·제품07:50/08:00·Telegram 수신 인수와 구분합니다.

`test_finnhub_news_probe.py`는 개발용 Finnhub 제목 규칙·ID/정규 URL/정규 제목 중복·발행 창·기발송 제외·사건군 편성·허용 호스트·정상 HEAD 경유와 중간 페이지/403/루프/위험 주소 제외를 합성 입력과 MockTransport로 검사합니다. 실기사 의미 중복 전체나 운영 송신·이용 허가 검증이 아닙니다.

`test_etf.py`는 SPY/QQQ/DIA의 USD·동일 완료 거래일·원본 Close·분배금/분할·수정치·누락을 검사합니다. `test_am_edition.py`·`test_am_guards.py`는 뉴스 0~3건·5글 거절·07:30·권리/원문/사람 확인·정정·모의/실제 경계와 격리 PostgreSQL 저장/예약/철회·멱등·감사를, `test_am_migration.py`는 base/0001→0002·downgrade·4번째 저장/5번째 거절을 검사합니다. DB 시험은 명시적 시험 URL이 필요합니다.

`uv run pytest tests/test_news_input.py`는 N01·N02 공통 입력의 출처/원매체, 발행 정밀도·최초 조회/확보/재확인, 본문 충분성·절단·해시, 권리 상태, 정상 발견 0건/새 버전 0건/부분 실패를 검사합니다. 합성 본문과 보존된 Exa 메타데이터를 사용하고 소켓 연결을 차단합니다. 실기사 충분성 자동 판정이나 Exa/BLS 어댑터·DB/승인 통합 시험은 아닙니다.

`test_exa.py`는 MockTransport로 검색/캐시 본문·필수 scope·권리/예산·키 반향·도메인/시각·중복/충돌·재확인을, `test_bls_input.py`는 기존 CPI와 공통 입력의 기간/비교기준·발표/확보·정정·일정 실패를, `test_news_evaluation.py`는 권리/시각/본문/근거·값/범위/조건/GAAP·중복/승인 근거 변경 보류를 검사합니다. 이 세 파일은 공급자 실호출·외부 AI·AM/승인/DB 통합 인수를 뜻하지 않습니다.

`test_news_selection.py`는 합성 뉴스 12건과 입력 변형으로 권한·발행/확보 시각·주장 근거·관련성·중복/후속·선정 순서·편성 보류를 검증합니다. 입력의 중요성/관련성 검토를 자동으로 수행하는 모델 평가가 아니며 출력은 항상 발행 불가입니다.

`test_api*.py`는 미인증/CSRF/구버전/멱등 요청과 PostgreSQL schema·승인 트랜잭션을 구분해 검사합니다. 실자료나 운영 키를 사용하지 않습니다. PostgreSQL 통합 시험은 명시적으로 지정한 격리 DB의 `XFOLIO_TEST_DATABASE_URL`을 요구하며 설정이 없으면 skip합니다. 기본 `XFOLIO_DATABASE_URL`이나 `.env`를 자동 사용하지 않습니다.

프론트 검증은 `frontend/`에서 `npm test`, `npm run build`입니다(Windows PowerShell에서는 `npm.cmd`도 사용 가능). 실행 가능한 API 계약은 `uv run python -m xfolio.api.export_openapi`로 갱신하고 `contracts/openapi.json`과 대조합니다.

`npm run test:integration`은 명시한 loopback `XFOLIO_BROWSER_TEST_DATABASE_URL`의 격리 schema에서 실제 API·DB·HTTPS 브라우저를 연결하며 Google provider만 모의합니다. `test_dev_https.py`는 개발 TLS/프록시, `test_news_workflow.py`·`test_news_generation.py`는 권한·토큰·예산·SDK·검토 대기 초안 저장을 검사합니다. 실제 Google 로그인·유료 AI·외부 게시와 구분합니다.

`test_market.py`는 두 지수의 완료 거래일·종가·등락률, 주말·휴장·서머타임·조기 마감, 결측·오래된 데이터·중복 날짜·제공처 오류, CLI 텍스트/JSON 출력을 확인합니다. 모든 시험에서 Yahoo 네트워크 요청을 차단하고 합성 응답을 사용합니다.

실제 데이터 확인은 별도로 `uv run xfolio market-close --json`을 실행합니다. 이 명령은 조회만 하며 X 게시를 수행하지 않습니다.

제품 ETF 조회는 `uv run xfolio etf-close --json`, `market-close`는 legacy 지수 조회입니다. `tests/legacy_pm_history.py`는 예전 PM 자료를 격리 DB에 만드는 시험 fixture이며 제품 진입점은 아닙니다. 기존 CPI 의미·길이 검사는 유지하고 PM 생성·승인은 차단, 조회·보류·과거 멱등 응답을 검사합니다. `frontend/e2e-live`는 실제 HTTPS/API/DB에서 AM 4글의 세 확인·예약·철회를 검증하며 모의 Google/입력 전제와 실제 공급자/AI/X를 구분합니다.
