# T06 자동 실행·실제 수집·Telegram 계약

- 기준: 2026-11-05, Asia/Seoul
- 상태: 서버 수집 연결·무통신/격리 DB 검증 완료. 실제 정시 수신·운영 인수 전.
- 관련: [계획](../../plans/자동_실행과_Telegram_전송.md) · [공통 계약](병렬_개발_공통_계약.md) · [11/4 첫 구현](../../logs/2026-11-04_자동_실행과_Telegram_전송.md) · [11/5 수집 연결](../../logs/2026-11-05_자동_수집과_아침_준비_연결.md)

## 입력과 실행 경계

`MorningWorker`는 신뢰하는 서버의 `calendar(day, now)`·`collect_inputs(day, frozen_at)`·T04 `NewsletterStore`·공용 설정을 읽는 `TelegramOutboxStore`·전송 adapter·clock을 받는다. 주말 또는 개장 false/미확인은 `collect_inputs` 전에 차단한다.07:50 입력 고정·08:00 이상08:10 미만 송신이며 마감 후 catch-up은 없다. 휴장/미확인/누락은 본문 없는 `operations_events(kind=newsletter_worker)`에 하루/사유별 멱등 기록한다.

`python -m xfolio.jobs.worker` 또는 `--once`는 합성 무통신 미리보기다. `--schedule`도 기본 mock이며 APScheduler3.x·KST로 월~금07:50 준비,08:00~08:09 매분 안전 재검사한다. 실제 발송은08시부터며 이후 분은429의 안전 재시도 점검이다. scheduler 미스파이어·다중 프로세스 여부와 별개로 DB 유일키/점유가 중복을 막는다.

`--live --once --phase send`는 명시 서버 설정과 기존 live 편성만 사용하는 송신 경로다. 이번 작업에서 실행하지 않았다. `XFOLIO_WORKER_LIVE_ACCEPTED=true`·명시 `XFOLIO_WORKER_DATABASE_URL`·`XFOLIO_TELEGRAM_BOT_TOKEN`·양수 단일 `XFOLIO_TELEGRAM_CHAT_ID`가 필요하다. `XFOLIO_RECIPIENT_SCOPE` 기본self, `XFOLIO_MONTHLY_BUDGET_KRW` 최대50000이다. 비밀은 `.env`에서 자동 읽거나 화면/로그에 노출하지 않는다. Telegram receipt의 chat.id/type=private도 대조한다.

`--live --phase prepare`와 `--live --schedule`은11/5부터 `LiveCollectionResources`로 KIS/Finnhub/공식 발표·OpenAI와 공통 DB를 구성한다. 서버 환경의 `KIS_APP_KEY`, `KIS_APP_SECRET`, 선택 `KIS_BASE_URL`, `FINNHUB_API_KEY`, `OPENAI_API_KEY`, **`XFOLIO_GENERATION_LIMITS_FILE`**이 추가로 필요하다. limits는 기존 `GenerationLimits` JSON이며 유효한 단가·출처·만료와 요청 토큰 상한이 있어야 한다. 키/단가/명시limits가 없으면 외부 호출 전에 실패하며 무료 결과나 추정 단가로 공식 요약을 성공 처리하지 않는다. 단독send에는 기존 준비편성/전송 설정만 필요하다. 환경의 acceptance 문자열은 운영 인수 완료를 뜻하지 않는다.

## 07:50 고정·단일 준비·실제 수집

`jobs/collection.py`의 `PreparationStore.claim(day)`는07:50 이상07:51 미만에 시작하는1분 유예를 허용한다. 설정/관심종목/종목정보 행을 하나의 DB 트랜잭션에서 잠그고 revision·순서·전체 설정을 고정한다. 설정/관심목록의 `updated_at`, 종목정보의 `retrieved_at`이07:50 이후면 그날 준비를 보류한다. DB 잠금을 기다린 후 유예가 지났어도 보류한다.07:50 이전의 호출은 준비claim을 만들지 않아 정상 예약을 가로막지 않는다. 시각은 신뢰하는 실제clock이며 과거 입력을 실제 현재호로 소급하지 않는다.

외부 요청 전에 `operations_events(kind=newsletter_prepare, scope=수신자, unique_key=대상일)`를 저장한다. 같은 날짜의 두 프로세스가 준비해도 외부수집·AI요약은 한 번만 실행한다. 중단된running이나실패는 자동으로 다시 수집/요약하지 않는다. 저장완료는 기존 결과를 반환한다. 이 claim은 가격/기사 본문 없이 설정·종목메타·참조ID만90일 보관하며 `PreparationStore.purge_expired(now=...)`로 삭제한다.

`LiveMorningPreparation.prepare()`는 고정 이후 **KIS 휴장 확인→KIS 종가/T02 저장→T03 Finnhub+공식 발표/허용 요약→T03 저장→T04 원본 대조/편성 저장→live outbox**를 연결한다. 휴장일에는 휴장 확인 이후 가격·뉴스·AI 호출이 없다. 주말에는 휴장 조회도 건너뛴다. 출처/요약 실패는 기존 T03 집계와 T04 partial/failed에 남기며 정상 0건을 구분한다. 이전 confirmed 호의 뉴스 동결 시각을 다음 선정의 last_success로 쓰고, confirmed/unknown 뉴스 키는 제외한다.

AI는 기존 `summarize`·`OpenAIGenerationClient`와 `SQLWorkflowStore` 계보의 `CappedWorkflowStore`를 사용한다. 기존 `usage_ledger`와 같은 예산 잠금에서 전체 reserved/estimated/confirmed를 합산해 최대 50000원과 서버의 더 낮은 한도를 검사한다. 08:10 이후 새 요약 요청은 차단한다. 실제 유료 호출과 정시 관측은 별도 실행 근거가 필요하다.

## 영속 상태와 경쟁

0007은0006 설정을 부모로 하고 `telegram_outbox`, `telegram_outbox_parts`, `telegram_send_attempts`를 추가한다. 수신자+KST 날짜+morning+mock/live 유일 키다. 모의 성공은 실제 성공/기발송 뉴스로 기록하지 않는다. outbox/조각/시도에 가격·뉴스 본문·chat ID·bot token을 저장하지 않으며 원문은 T04 편성의 유효 본문으로만 조회한다.

claim은 공용 AI 예산 advisory lock·outbox row lock과 같은 트랜잭션에서 설정 서비스 `get(conn=...,for_update=True)`·관심종목·가격/뉴스 원본·개장일·월 비용원장 합계를 대조하고 T04 저장 검사를 호출한다. 각 조각도 직전에 같은 검사를 다시 수행한다. 송신 중인 외부 요청을 원격으로 취소할 수 있다고 가정하지 않으며 검사 직후 발생한 관리 변경은 다음 조각의 검사부터 적용한다.

순서는 pending→sending→confirmed/partial/failed/unknown/retryable_failure다. 부분 성공 뒤429도 성공 조각은 건너뛰고 미성공 조각만 retry_after 이후 재검사한다. 중지/마감이 되면 이미 성공한 조각을 보존해partial로 끝낸다.429 재시도 시각이08:10 이상이면 종료한다. timeout·잘못된 receipt·5xx·요청 후 예외는unknown이며 재전송하지 않는다.90초 lease가 지난sending은 재시작 복구에서unknown으로 정리한다. 시도 저장 commit 후 HTTP 호출하고 성공 receipt를 별도commit하므로 두 시스템 사이 원자성은 없다.

live 전체 성공은 T03 뉴스confirmed, live 부분/불명은 보수적으로unknown으로 기록해 중복 전달을 차단한다. 실제 조각별 기사 경계를 추정해 부분 발송을 전체confirmed로 처리하지 않는다. mock은 T03 전달 테이블을 쓰지 않는다.

## 조회·보존·시험

`list_deliveries(now=...,limit=50)`는 JSON 목록, `get_delivery(id,now=...)`는 조각/시도와 유효 본문을 반환한다. token/lease는 숨긴다. 메타데이터는 생성+365일이며 T04 본문은 원본90일/더 이른 만료부터None이다. `purge_expired(now=...)`가 outbox와하위 시도를cascade 삭제하고 자기 worker 상태 기록도 만료 삭제한다.

- [무통신 시험](../../../tests/test_telegram_worker.py): UTF-16분할·원문 보존, receipt/429 shape/timeout·비밀 비노출, 휴장 수집전 차단·시각·KST예약·기본mock.
- [격리 DB 시험](../../../tests/test_telegram_outbox_postgres.py):0007 업/다운/스냅샷·경쟁claim·mock/live분리·중복·현재중지/개장/예산/마감·429/부분·unknown/재시작·90/365일.
- [수집 설정·CLI 시험](../../../tests/test_worker_collection.py): 서버 환경만읽기·명시단가/키거절·live준비/예약자원구성·기본mock보존.
- [수집 연결 격리 DB 시험](../../../tests/test_worker_collection_postgres.py):07:50고정/늦은변경/잠금유예·중복/중단·실제T02/T03/T04저장·AI비용원장·휴장·정상0/partial/failed·unknown제외·이전호동결시각·90일준비claim보존.

실제본인수신·정시수집·운영재시작·AWS·T09오후 슬롯은 이번 검증 근거가 아니다.
