# 테스트

`uv run pytest`로 외부 API 없이 기능을 검증합니다.

`test_news_selection.py`는 합성 뉴스 12건과 입력 변형으로 권한·발행/확보 시각·주장 근거·관련성·중복/후속·선정 순서·편성 보류를 검증합니다. 입력의 중요성/관련성 검토를 자동으로 수행하는 모델 평가가 아니며 출력은 항상 발행 불가입니다.

`test_api*.py`는 미인증/CSRF/구버전/멱등 요청과 PostgreSQL schema·승인 트랜잭션을 구분해 검사합니다. 실자료나 운영 키를 사용하지 않습니다. PostgreSQL 통합 시험은 명시적으로 지정한 격리 DB의 `XFOLIO_TEST_DATABASE_URL`을 요구하며 설정이 없으면 skip합니다. 기본 `XFOLIO_DATABASE_URL`이나 `.env`를 자동 사용하지 않습니다.

프론트 검증은 `frontend/`에서 `npm test -- --run`, `npm run build`입니다. 실행 가능한 API 계약은 `uv run python -m xfolio.api.export_openapi`로 갱신하고 `contracts/openapi.json`과 대조합니다.

`npm run test:integration`은 명시한 loopback `XFOLIO_BROWSER_TEST_DATABASE_URL`의 격리 schema에서 실제 API·DB·HTTPS 브라우저를 연결하며 Google provider만 모의합니다. `test_dev_https.py`는 개발 TLS/프록시, `test_news_workflow.py`·`test_news_generation.py`는 권한·토큰·예산·SDK·검토 대기 초안 저장을 검사합니다. 실제 Google 로그인·유료 AI·외부 게시와 구분합니다.

`test_market.py`는 두 지수의 완료 거래일·종가·등락률, 주말·휴장·서머타임·조기 마감, 결측·오래된 데이터·중복 날짜·제공처 오류, CLI 텍스트/JSON 출력을 확인합니다. 모든 시험에서 Yahoo 네트워크 요청을 차단하고 합성 응답을 사용합니다.

실제 데이터 확인은 별도로 `uv run xfolio market-close --json`을 실행합니다. 이 명령은 조회만 하며 X 게시를 수행하지 않습니다.
