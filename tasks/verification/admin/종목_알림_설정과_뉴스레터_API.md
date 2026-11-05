# T05 종목·알림 설정과 뉴스레터 API

- 기준: 2026-11-04 / 갱신: 2026-11-05, Asia/Seoul
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
| GET `/api/newsletter-operations/summary` | 서버 확인시각·한국 당일 개장 확인/미확인·현재 설정·관심목록·오늘 편성·KST 당월 비용 원장·시세 신선도·뉴스 수집·최근 발송/실패·worker 상태 |

`NotificationSettingsStore(engine).get(conn=None, for_update=False)`는 서버의 단일 설정을 읽고 worker 트랜잭션의 row lock에 참여한다. `update(expected_revision, changes, actor, now)`는 row lock 아래 변경·revision 증가·감사를 함께 commit한다. T02 관심목록 서비스도 같은 DB connection의 transaction-bound adapter로 호출해 기존 코드 검사를 재사용하고 감사 실패 시 함께 rollback한다. API 변경값으로 과거 편성/발송 결과를 덮어쓰지 않는다.

0006은 기본 아침true·중지false·오후false·revision1을 생성한다. 설정·관심목록 변경 감사는 `notification_setting_audit`에 가격 없는 최소 before/after·actor·revision·UTC시각을365일 보존한다. `purge_expired(now=...)`는 만료 감사만 삭제한다. 아침true 기본값은 운영 환경의 live 송신 활성화 승인을 뜻하지 않는다.

## 화면과 검증

기본5메뉴는 뉴스레터 관측·설정용이며 매회 승인 버튼을 제공하지 않는다. 설정 변경은 응답 후 최신revision을 다시 읽고409/응답 불명은 자동 변경 재시도를 하지 않는다. 조회 실패 시 이전 자료를 정상으로 보여주지 않는다.14/16시 켜기는 비활성이다. 관심목록은 검색/지원확인·추가·비활성·위아래 순서 변경을 제공하며 최소1종목/최대10개를 서버에서 재검사한다.

이전 X/AM 검토 UI·단위시험은 `LegacyApp.tsx`에 보존하고 브라우저 회귀는 `/?legacy=1`을 명시한다. 신규 UI와 legacy 시험을 분리해 이전 검증을 새 Telegram 송신 인수로 보고하지 않는다.

- 무통신 API: 인증·CSRF·strict 입력·revision·오후거절·미연결·만료 세션.
- 격리PG: 0006 업/다운/재적용·DDL스냅샷·초기값·동시revision·감사·감사실패 시 설정/관심목록 rollback·365일 삭제·T02 이력 유지.
- UI 단위: 신규5메뉴·휴장·설정CSRF/revision·409·이력 미연결·종목순서. 기존12건 유지.
- Playwright: 신규5메뉴→중지→종목검색1건, legacy4건. HTTPS·실제 API/PG의 legacy 회귀2건도 별도 수행.

첫 구현 결과는 [11/4 수행 기록](../../logs/2026-11-04_관리자_종목과_알림_설정.md)에 보존한다. 11/5 실제 DB 대시보드 연결과 검증은 [별도 수행 기록](../../logs/2026-11-05_관리자_대시보드_실제_DB_연결.md)에 남긴다. 실제 Google·실자료 수집/송신을 연결하는 제품 인수와 운영 PC/휴대폰 접근은 후속이다.

## 11/5 실제 DB 대시보드 계약

대시보드는 서버의 `checked_at`을 표시하고 수동 조회와 60초 갱신을 제공한다. 조회 실패 시 이전 성공 응답의 운영 카드를 숨겨 오래된 자료를 정상으로 표시하지 않는다. 모든 집계는 읽기이며 수집·편성·송신을 시작하지 않는다.

| 항목 | 집계와 판정 |
| --- | --- |
| 비용 | `usage_ledger`의 KST 당월 `confirmed`·`reserved`·`estimated`를 합산하고 `released`는 제외한다. `XFOLIO_MONTHLY_BUDGET_KRW` 또는 정책 기본 50,000원과 대조한다. 비정상 설정/원장·예산 초과·기록 없음을 구분한다. 기록 없음은 실비 0원이 아니며 청구서 전체 대조를 뜻하지 않는다. 원장 payload는 반환하지 않는다. |
| 시세 | 현재 관심목록 revision의 최신 완료 run을 읽고, 당일 KIS 거래일 coverage와 현재 시각 기준 최근 완료 2거래일을 대조한다. 종목별 snapshot 모델·해시·거래일·시각·90일 만료·정정 버전을 검사한다. 누락/만료/변조/이전 거래일/최신 정정으로 대체됨을 구분한다. |
| 출처·시각 | 연결된 불변 T04 편성의 무결성을 확인한 뒤 실자료/합성/시험을 판정한다. 편성 없는 run은 실자료 여부 미확인이다. 가격 기준시각 미제공·예정 마감·조회시각을 구분하고 제공 지연은 미측정으로 표시한다. 만료 snapshot은 가격·날짜 payload를 반환하지 않는다. |
| 뉴스 | 보존기한 이내 최신 run의 기준/완료시각·선정 수·남아 있는 선정 메타데이터 수·출처별 상태/오류 코드를 읽는다. 정상 0건과 부분 실패/전체 실패, 오늘 아침과 이전 수집, 합성/미확인을 구분한다. 원본 payload나 비밀은 반환하지 않는다. |
| 발송·worker | T06 읽기 서비스의 보존기한 이내 최신 10건과 그중 실패/부분 성공/결과 불명/재시도 대기를 표시한다. 모의/실제 송신을 구분하며 claim token·lease는 반환하지 않는다. `newsletter_prepare`·`newsletter_worker` 중 최신 유효 운영 이벤트의 준비/발송 단계·허용 상태·안전한 사유 코드만 표시한다. 08시 이전 준비 진행/실패도 관측한다. |

격리 PostgreSQL과 API 시험은 미관측·실자료 연결·뉴스 정상 0건/부분/실패·합성·편성 없는 run·주말·거래일 불일치·누락/정정·마감 후 기준일 변경·KST 월경계 비용·결과 불명 발송·90일 만료·인증과 Decimal JSON 응답을 검사한다. 준비 진행/실패·비정상 상태/사유·만료 이벤트의 제외도 확인한다. UI 단위시험은 실제 집계 응답 표시·준비/발송 단계 구분과 재조회 실패 시 이전 상태 숨김을 검사한다.
