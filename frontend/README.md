# XFolio 관리자

React·TypeScript·Vite의 개인용 뉴스레터 관리자입니다. 기본 화면은 대시보드·뉴스레터·발송 이력·관심 종목·알림 설정의5메뉴입니다. 같은 origin의 FastAPI `/api`만 사용하고 브라우저에 공급자·DB·Google·Telegram 비밀을 저장하지 않습니다.

```powershell
cd frontend
npm ci
npm run dev
npm run build
npm test
```

개발 서버는 `127.0.0.1:5173`이고 `/api`를 `127.0.0.1:18443`으로 전달합니다. 실제 Google 로그인은 FastAPI의 허용 운영자·OIDC·HTTPS 설정이 필요합니다. 설정 미완료 오류를 개발 로그인으로 우회하지 않습니다. 화면은 실제 API 결과만 표시합니다.

`npm run build`는 TypeScript 검사와 정적 파일 생성을 수행합니다. 결과는 `dist/`에 생성되며 배포에서는 같은 origin의 `/api`를 서버로 전달해야 합니다.

## 회귀 테스트

`npm test`는 신규5메뉴·휴장 미발송·설정/종목 revision·CSRF·발송 미연결을 검사합니다. 기존 로그인 안내·합성 자료/근거 누락 승인 차단·409·응답 불명 재전송·최신 조회 실패 시험도 보존했습니다.

종목/알림 변경은 실제 API의 세션·CSRF·revision 검사를 통과해야 합니다.14/16시 알림은 T09 인수 전 비활성화되어 있으며 브라우저 임의 변경도 API가 거절합니다. 발송 이력은 T06 outbox 읽기 서비스를 사용합니다. 구현 코드만으로 실제 수신/운영 인수를 완료한 것은 아닙니다. 기존 검토 UI는 `/?legacy=1`로 접근하는 과거 회귀 자산입니다.

새 AM은 첫 글을 ETF 종가(USD)로 표시하고 세 확인 항목을 현재 버전에 묶어 전송합니다. 재조회/버전/결정 revision 변경이나 조회 실패 후에는 확인을 초기화합니다. `transport_mode=mock`은 모의 송신 편성으로 표시하고 PM은 과거 이력 조회·보류만 허용합니다.

```powershell
npm run test:e2e
```

Playwright는 전용 `127.0.0.1:5177` 서버를 띄워 API를 브라우저 안에서 모의합니다. 로컬 Windows는 설치된 Microsoft Edge를 사용합니다. CI에서는 `CI=true`로 Chromium을 선택하며 먼저 `npx playwright install --with-deps chromium`을 실행합니다. 실제 API·DB·Google·X·Telegram과 연결하지 않으므로 이 결과를 전체 제품 E2E/외부 연동 합격으로 해석하지 않습니다. 문서의 합성 입력을 제품의 실제 자료로 바꾸지 않습니다.

브라우저 시험은 미인증 로그인 안내, 목록→상세의 근거 표시, 409 뒤 재조회, 응답 불명 뒤 같은 멱등 키·본문 재전송을 검증합니다. `test-results/review-detail.png`는 격리된 모의 화면의 확인용 이미지이며 실제 운영 결과가 아닙니다.

## 실제 API·PostgreSQL 브라우저 통합 시험

```powershell
# 개발용 PostgreSQL을 별도로 준비하고 명시한 loopback 시험 DB만 사용합니다.
$env:XFOLIO_BROWSER_TEST_DATABASE_URL = '<격리 시험 PostgreSQL URL>'
npm run build
npm run test:integration
```

이 시험은 `https://127.0.0.1:8447`에 테스트 전용 서버를 시작합니다. 권한이 있는 loopback PostgreSQL URL이 필요하며 기존 운영 DB 환경변수나 `.env`를 자동으로 읽지 않습니다. 새로운 `xfolio_browser_e2e_` 접두사 schema에 Alembic migration을 적용하고, 정상 종료 때 해당 schema만 정리합니다. 다른 테이블·schema를 대체하지 않습니다.

브라우저 API 응답을 모의하지 않고 실제 FastAPI·PostgresStore·서버 세션을 호출합니다. Google의 외부 요청 경계는 테스트 provider로 대체하며 가격/기사/생성 입력도 격리 fixture 전제이므로 실제 Google JWT·공급자·AI 성공을 뜻하지 않습니다. HTTPS Secure/HttpOnly 쿠키, PM 신규 승인 차단/보류·CSRF/Origin·로그아웃과 AM ETF+뉴스 4글의 세 확인·DB 예약·철회를 검증합니다. 송신 모드는 mock이며 X·Telegram 연동은 수행하지 않습니다.

테스트 인증서는 `.cache/browser-e2e/`에 두고 시험 context에서만 자체서명 인증서를 허용합니다. OS 신뢰 저장소는 변경하지 않습니다. 이미지 `test-results/live-api-held.png`도 격리된 시험 결과입니다.

새 뉴스레터의 실제 HTTPS·API·DB 연결은 같은 시험 DB 환경변수와 build 후 `npm run test:newsletter`로 확인합니다. 시험 schema에서 worker/수집 저장·비용 원장·뉴스레터/발송 상세·설정 중지를 연결하며 외부 제공처/AI/Telegram/Google은 시험 대역입니다. `test-results/t07-dashboard.png`의 실자료/live 표시는 이 분기 검사용 fixture 값이며 실제 외부 수집·송신의 관측 자료가 아닙니다. 실제 무료 조회·Telegram 통신 결과는 [T07 기록](../tasks/logs/2026-11-05_아침_뉴스레터_통합_인수.md)을 따릅니다.

## 소스 위치

| 경로 | 역할 |
| --- | --- |
| `src/main.tsx` · `src/app/App.tsx` | React 기동·현재/legacy 앱 선택 |
| `src/features/newsletter/NewsletterApp.tsx` | 현재 관리자 세션·로그인·메뉴·로그아웃 |
| `src/features/newsletter/pages/` | Dashboard·Newsletters·Deliveries·Detail·Watchlist·Settings 메뉴별 화면 |
| `src/features/newsletter/components/` | 오류/상태 안내·뉴스레터 표 |
| `src/features/newsletter/types.ts` · `format.ts` | 관리자 응답 타입·한글 상태/시각/금액 표시 |
| `src/features/legacy/` | 이전 X 편성 검토 화면·해당 API/타입·회귀 시험 |
| `src/shared/` | 공용 HTTP 오류/요청과 세션 타입 |
| `src/styles/` · `src/test/` | 공용 CSS·Vitest 설정 |
| `tests/e2e/mock/` | 모의 API 브라우저 회귀 |
| `tests/e2e/legacy_api/` · `newsletter_api/` | 실제 HTTPS/API·격리 DB 연결 시험 |

UI 단위 시험은 각 기능 폴더에 둔다. 실행 스크립트·URL·포트는 그대로이며 `.test.tsx` 경로를 직접 지정할 때는 새 위치를 사용한다. 새 메뉴는 `pages/`, 공용 통신은 `shared/`, 기존 X 전용 코드는 `legacy/`에 추가한다.

HTTPS/API 브라우저 시험의 기본 포트는8447이다. 이미 사용 중이면 `XFOLIO_BROWSER_TEST_PORT`로 비어 있는 포트(예:18447)를 지정한다.3000/8000은 허용하지 않는다. 실제 관리자8443/API18443·DB55439 설정과는 별개다.
