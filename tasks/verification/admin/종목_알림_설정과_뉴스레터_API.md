# T05 종목·알림 설정과 뉴스레터 API

- 기준: 2026-11-04, Asia/Seoul
- 관련: [계획](../../plans/관리자_종목과_알림_설정.md) · [공통 계약](../integration/병렬_개발_공통_계약.md)

## 서버 계약

기존 Google OIDC·Secure/HttpOnly 세션·허용 운영자 검사를 재사용한다. 변경은 동일 Origin과 `X-CSRF-Token`이 필요하다. API가 DDL·외부 수집·즉시 전송을 실행하지 않는다. 브라우저가 보내는 token/수신자/임의 시각은 허용 입력이 아니다.

| 경로 | 계약 |
| --- | --- |
| GET/PATCH `/api/notification-settings` | `MorningSettings`. PATCH는 `expected_revision`과 변경할 네 boolean만 허용. revision 충돌409, T09 전 오후true409, 문자열/숫자 boolean422 |
| GET `/api/instruments?q=...` | T02 공식 종목 마스터 검색. 이름/코드·시장/통화·지원 확인 상태 반환 |
| GET/PUT `/api/watchlist` | 활성 코드1~10개·순서·revision·종목정보. PUT은 현재revision·고유6자리 코드·지원 확인을 T02 서비스에서 검사 |
| GET `/api/newsletters` | 날짜·상태 필터, 최대50개. 원본 보존기한 이내 편성만 반환 |
| GET `/api/newsletters/{key}` | T04 해시/모델 검사를 거친 불변 편성·본문·출처/검사 사유. 만료/없음404, 변조503 |
| GET `/api/deliveries`, `/{key}` | T06 읽기 서비스 호출. 모듈 미연결503, 실제0건과 구분. 자동 재전송 API 없음 |
| GET `/api/newsletter-operations/summary` | 한국 당일 개장 확인/미확인·현재 설정·관심목록·오늘 편성. 비용/시세 신선도 미연결/미관측 구분 |

`NotificationSettingsStore(engine).get(conn=None, for_update=False)`는 서버의 단일 설정을 읽고 worker 트랜잭션의 row lock에 참여한다. `update(expected_revision, changes, actor, now)`는 row lock 아래 변경·revision 증가·감사를 함께 commit한다. T02 관심목록 서비스도 같은 DB connection의 transaction-bound adapter로 호출해 기존 코드 검사를 재사용하고 감사 실패 시 함께 rollback한다. API 변경값으로 과거 편성/발송 결과를 덮어쓰지 않는다.

0006은 기본 아침true·중지false·오후false·revision1을 생성한다. 설정·관심목록 변경 감사는 `notification_setting_audit`에 가격 없는 최소 before/after·actor·revision·UTC시각을365일 보존한다. `purge_expired(now=...)`는 만료 감사만 삭제한다. 아침true 기본값은 운영 환경의 live 송신 활성화 승인을 뜻하지 않는다.

## 화면과 검증

기본5메뉴는 뉴스레터 관측·설정용이며 매회 승인 버튼을 제공하지 않는다. 설정 변경은 응답 후 최신revision을 다시 읽고409/응답 불명은 자동 변경 재시도를 하지 않는다. 조회 실패 시 이전 자료를 정상으로 보여주지 않는다.14/16시 켜기는 비활성이다. 관심목록은 검색/지원확인·추가·비활성·위아래 순서 변경을 제공하며 최소1종목/최대10개를 서버에서 재검사한다.

이전 X/AM 검토 UI·단위시험은 `LegacyApp.tsx`에 보존하고 브라우저 회귀는 `/?legacy=1`을 명시한다. 신규 UI와 legacy 시험을 분리해 이전 검증을 새 Telegram 송신 인수로 보고하지 않는다.

- 무통신 API: 인증·CSRF·strict 입력·revision·오후거절·미연결·만료 세션.
- 격리PG: 0006 업/다운/재적용·DDL스냅샷·초기값·동시revision·감사·감사실패 시 설정/관심목록 rollback·365일 삭제·T02 이력 유지.
- UI 단위: 신규5메뉴·휴장·설정CSRF/revision·409·이력 미연결·종목순서. 기존12건 유지.
- Playwright: 신규5메뉴→중지→종목검색1건, legacy4건. HTTPS·실제 API/PG의 legacy 회귀2건도 별도 수행.

실제 결과와 제약은 [수행 기록](../../logs/2026-11-04_관리자_종목과_알림_설정.md)에 기록한다. 신규UI와 실제Google/T06이력·가격/뉴스 원본 전체를 연결하는 제품 인수, 비용/신선도 대시보드 연결, 운영 PC/휴대폰 접근은 후속이다.
