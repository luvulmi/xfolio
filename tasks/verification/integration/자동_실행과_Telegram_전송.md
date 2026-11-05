# T06 자동 실행·Telegram 첫 구현 계약

- 기준: 2026-11-04, Asia/Seoul
- 상태: 첫 구현·무통신/격리 DB 검증. 전체 T06 및 실제 운영 인수 전.
- 관련: [계획](../../plans/자동_실행과_Telegram_전송.md) · [공통 계약](병렬_개발_공통_계약.md) · [결과](../../logs/2026-11-04_자동_실행과_Telegram_전송.md)

## 입력과 실행 경계

`MorningWorker`는 신뢰하는 서버의 `calendar(day, now)`·`collect_inputs(day, frozen_at)`·T04 `NewsletterStore`·공용 설정을 읽는 `TelegramOutboxStore`·전송 adapter·clock을 받는다. 주말 또는 개장 false/미확인은 `collect_inputs` 전에 차단한다.07:50 입력 고정·08:00 이상08:10 미만 송신이며 마감 후 catch-up은 없다. 휴장/미확인/누락은 본문 없는 `operations_events(kind=newsletter_worker)`에 하루/사유별 멱등 기록한다.

`python -m xfolio.jobs.worker` 또는 `--once`는 합성 무통신 미리보기다. `--schedule`도 기본 mock이며 APScheduler3.x·KST로 월~금07:50 준비,08:00~08:09 매분 안전 재검사한다. 실제 발송은08시부터며 이후 분은429의 안전 재시도 점검이다. scheduler 미스파이어·다중 프로세스 여부와 별개로 DB 유일키/점유가 중복을 막는다.

`--live --once --phase send`는 명시 서버 설정과 기존 live 편성만 사용하는 송신 경로다. 이번 작업에서 실행하지 않았다. `XFOLIO_WORKER_LIVE_ACCEPTED=true`·명시 `XFOLIO_WORKER_DATABASE_URL`·`XFOLIO_TELEGRAM_BOT_TOKEN`·양수 단일 `XFOLIO_TELEGRAM_CHAT_ID`가 필요하다. `XFOLIO_RECIPIENT_SCOPE` 기본self, `XFOLIO_MONTHLY_BUDGET_KRW` 최대50000이다. 비밀은 `.env`에서 자동 읽거나 화면/로그에 노출하지 않는다. Telegram receipt의 chat.id/type=private도 대조한다.

**실제 T02/T03 수집 adapter·유료 공식 요약을 자동 구성하는 연결은 미완료**다. 따라서 `--live --phase prepare`와 `--live --schedule`은 `live_collection_adapter_not_accepted`로 차단한다. 주입 가능한 준비/송신 골격과 실제 제공처 자동 수집 완성은 구분한다. 환경 변수의 acceptance 문자열만으로 실제 운영 인수가 끝났다고 보지 않는다.

## 영속 상태와 경쟁

0007은0006 설정을 부모로 하고 `telegram_outbox`, `telegram_outbox_parts`, `telegram_send_attempts`를 추가한다. 수신자+KST 날짜+morning+mock/live 유일 키다. 모의 성공은 실제 성공/기발송 뉴스로 기록하지 않는다. outbox/조각/시도에 가격·뉴스 본문·chat ID·bot token을 저장하지 않으며 원문은 T04 편성의 유효 본문으로만 조회한다.

claim은 공용 AI 예산 advisory lock·outbox row lock과 같은 트랜잭션에서 설정 서비스 `get(conn=...,for_update=True)`·관심종목·가격/뉴스 원본·개장일·월 비용원장 합계를 대조하고 T04 저장 검사를 호출한다. 각 조각도 직전에 같은 검사를 다시 수행한다. 송신 중인 외부 요청을 원격으로 취소할 수 있다고 가정하지 않으며 검사 직후 발생한 관리 변경은 다음 조각의 검사부터 적용한다.

순서는 pending→sending→confirmed/partial/failed/unknown/retryable_failure다. 부분 성공 뒤429도 성공 조각은 건너뛰고 미성공 조각만 retry_after 이후 재검사한다. 중지/마감이 되면 이미 성공한 조각을 보존해partial로 끝낸다.429 재시도 시각이08:10 이상이면 종료한다. timeout·잘못된 receipt·5xx·요청 후 예외는unknown이며 재전송하지 않는다.90초 lease가 지난sending은 재시작 복구에서unknown으로 정리한다. 시도 저장 commit 후 HTTP 호출하고 성공 receipt를 별도commit하므로 두 시스템 사이 원자성은 없다.

live 전체 성공은 T03 뉴스confirmed, live 부분/불명은 보수적으로unknown으로 기록해 중복 전달을 차단한다. 실제 조각별 기사 경계를 추정해 부분 발송을 전체confirmed로 처리하지 않는다. mock은 T03 전달 테이블을 쓰지 않는다.

## 조회·보존·시험

`list_deliveries(now=...,limit=50)`는 JSON 목록, `get_delivery(id,now=...)`는 조각/시도와 유효 본문을 반환한다. token/lease는 숨긴다. 메타데이터는 생성+365일이며 T04 본문은 원본90일/더 이른 만료부터None이다. `purge_expired(now=...)`가 outbox와하위 시도를cascade 삭제하고 자기 worker 상태 기록도 만료 삭제한다.

- [무통신 시험](../../../tests/test_telegram_worker.py): UTF-16분할·원문 보존, receipt/429 shape/timeout·비밀 비노출, 휴장 수집전 차단·시각·KST예약·기본mock.
- [격리 DB 시험](../../../tests/test_telegram_outbox_postgres.py):0007 업/다운/스냅샷·경쟁claim·mock/live분리·중복·현재중지/개장/예산/마감·429/부분·unknown/재시작·90/365일.

실제본인수신·정시수집·운영재시작·AWS·T09오후 슬롯은 이번 검증 근거가 아니다.
