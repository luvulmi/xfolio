# 2주 MVP 구현 계약 · API·저장·예약·알림

- 갱신: 2026-10-28, Asia/Seoul
- 상태: **구현 전 계약**. 실제 연동·성능·운영 권한의 검증 결과가 아님
- 범위: [요구사항](../../docs/요구사항.md) · [운영 정책](../../docs/운영_정책.md) · [우선순위](../plans/개발_우선순위.md)

## 화면과 실행 경계

- React·TypeScript·Vite: 대시보드(편성별 후보/상태·최근 실행·비용/알림 요약)와 후보 상세(근거·완성 글·검증·승인/보류)의 **2화면**. Google 로그인은 진입 흐름이다.
- 같은 HTTPS origin에서 정적 React와 `/api`를 제공한다. FastAPI만 DB에 접근하고 브라우저에 DB/공급자/봇 비밀을 전달하지 않는다. API는 수집·AI·X 작업을 직접 오래 실행하지 않는다.
- Google OIDC callback은 FastAPI가 처리한다. 운영자 이메일/issuer/검증 상태 확인, Secure·HttpOnly·SameSite 쿠키와 만료·CSRF 검사를 둔다. OAuth 공급자 토큰은 브라우저 저장소에 보관하지 않는다. 회원가입·역할 관리 UI는 없다.
- 기존 `MorningPreview(synthetic=True, can_publish=False)`와 가상 `preview_drafts`는 유지한다. 실제 초안/승인/발행은 별도 모델로 구현해 가상 게시 차단을 해제하지 않는다.

## FastAPI 8개 endpoint

| 메서드·경로 | 역할·중요 조건 |
| --- | --- |
| `GET /api/auth/login` | Google 로그인 시작·state/nonce |
| `GET /api/auth/callback` | callback·운영자 검사·세션 생성 |
| `GET /api/auth/me` | 인증 상태·운영 모드·허용 동작 |
| `POST /api/auth/logout` | CSRF 확인·세션 해제 |
| `GET /api/drafts` | 날짜/편성/상태와 제한된 페이지 크기, 최근 후보 |
| `GET /api/drafts/{id}` | 정확한 초안 버전·허용 근거·검증·발행 결과 |
| `POST /api/drafts/{id}/decision` | `approve/hold`, `expected_version`. 미인증401·비허용403·구버전/경쟁/기한 경과409·형식422 |
| `GET /api/operations/summary` | 마지막 실행·누락·예산 원장·발행/알림 상태. 외부 청구 총액이라고 표시하지 않음 |

승인은 DB 트랜잭션에서 현재 버전·validation·편성 기한·사용 한도·담당 운영자를 확인한다. 같은 요청/버전 중복 결정은 멱등 처리하고, 다른 버전에는 승인 이월을 금지한다. 프론트의 버튼 비활성화만으로 권한을 보장하지 않는다. 모드 변경·직접 X 게시 API는 추가하지 않는다.

## PostgreSQL 8개 저장 단위

SQLAlchemy Core·Alembic으로 migration과 작은 저장 인터페이스를 둔다. 기존 SQLite 모델을 재사용하고 복잡한 ORM/세부 claim 테이블 분해는 미룬다. 실제 DDL과 권한은 구현 때 검증한다.

| 테이블 | 필수 정보·제약 |
| --- | --- |
| `news_cursors` | 제공처·질의버전·범위의 완료 위치, compare-and-set. partial/failed·공백은 전진 금지 |
| `collection_runs` | UUID·조회 창·수집 시각·complete/partial/failed·요청수·쿼터 스냅샷 |
| `evidence_bundles` | 출처ID·내용버전 유일, 사건 키·발행/수정/수집UTC·허용 근거/권한 범위. 미허용 텍스트 저장 금지 |
| `content_drafts` | 변경 불가 버전/hash·AM/PM·대상일·지수 snapshot·글 순서·근거 참조·검증 결과·synthetic 구분 |
| `publication_jobs` | 버전 참조·reviewed 승인 또는 auto 검증·예약시각·기한·점유·상태. 계정/날짜/AM 또는 PM의 편성 중복 예약 제약 |
| `publication_posts` | 글별 전송 전 기록·순서·사건/사실 버전·결과·X ID. 활성 예약/게시/unknown인 사건의 중복 claim 차단, 확실한 미전송 취소만 해제 |
| `usage_ledger` | 제공처별 요청·입출력 토큰·예상/예약/확정 비용. 상태 전이에 따라 정산 |
| `operations_events` | 장애/승인 감사·발신 대기 outbox·fingerprint·심각도·발생/복구·전송 시도·마지막 결과 |

API 역할은 조회·정확한 승인 변경에 필요한 권한만, worker는 수집/발행/비용/알림 기록 권한을 사용한다. migration 역할은 분리한다. DB URL·오류 원문·봇 토큰을 API/화면/로그에 노출하지 않는다.

## 단일 worker와 시각

APScheduler는 API와 다른 **worker 컨테이너 한 프로세스**에서 고정 시간표를 읽는다. replica=1·동일 job 중복 금지에 더해 DB 편성 키/상태 점유를 적용한다. Docker 재시작 뒤 지난 예약을 무조건 재생하지 않고 현재 시각·모드·근거·기한을 검사한다. [APScheduler의 다중 프로세스 주의](https://apscheduler.readthedocs.io/en/3.x/faq.html)

| 시각 KST | 동작 |
| --- | --- |
| 아침 07:00 준비·07:30 정보 기준 | 이전 아침 기준 이후의 정의된 수집 창을 처리. 기준 전 확보·완주하지 못한 필수 근거는 보류 |
| 07:45 검토 준비 목표 | 최대 3글의 검증된 버전 저장. reviewed 승인 대기 |
| 08:00 발행 목표·09:00 마감 | 해당 버전·모드·한도 검사 후 아침 발행. 지연·미승인은 보류 기록 |
| 09:00~17:00 매시간·17:30 최종 확인 | 07:30 이후의 마지막 완전 수집 위치부터 허용 겹침으로 후보 축적. 각 회차는 수집만, 즉시 게시 없음 |
| 17:30~17:45 | 17:30까지 발행된 기사의 최종 수집·대조·관련성/중요도·근거 검토. 필수 구간 complete일 때만 최대 2사건 동결 |
| 18:00 목표·18:10 마감 | PM batch를 최대 2개 독립 글로 순서대로 발행. 승인/auto gate가 없으면 보류. 18:10부터 새 전송/자동 재시도 금지 |

`morning`/`collect_news`/`prepare_evening`/`publish_due`의 도메인 함수와 같은 함수를 쓰는 수동 dry_run 명령을 준비한다. 실제 CLI 이름은 구현 시 확정한다. 별도 5분 승인 대기 Job은 제거한다. worker의 `publish_due`는 08:00~08:59와 18:00~18:09 안에서만 매분 DB를 확인해 정시와 늦은 승인을 처리한다. 밤새 불필요한 DB polling으로 Neon을 계속 활성화하지 않는다. 승인 변경은 웹 요청에서 DB에만 기록한다.

UTC로 원문 발행/수정·수집·동결·승인·전송 시각을 따로 남긴다. 아침 근거는 기존 R01, 저녁은 published_at≤17:30·최종 수집/근거 동결≤17:45를 적용한다. 17:45 뒤 새 근거를 더하면 기존 승인은 무효이며 마감 내 새 버전 검증이 필요하다. 최신성·근거 정정 충돌은 무조건 보류한다. complete는 선언된 질의·창·페이지 완주이며 제공처의 모든 뉴스 포괄성을 뜻하지 않는다.

## 발행·장애·Telegram

`prepared → validated → approved/auto_validated → scheduled → sending → published`를 기본 상태로 두고 `held/failed/partial/unknown/expired`를 구분한다. 첫 X 요청 전에 글별 발행 시도를 저장한다. 응답 불명·일부 성공은 자동으로 처음부터 재전송하지 않고 예약/비용을 보존한다.

| 이벤트 | 처리·알림 |
| --- | --- |
| 자동 검증/승인 처리 예외·검증 실패 버전의 발행 시도·구버전 충돌 누적 | 발행 보류/auto 중단, 원인 코드·버전 기록. 장애 알림 1회. 일반 사용자 구버전 승인 409 하나마다 알리지는 않음 |
| 제공처 quota/credit 소진·월 예산 80%·초과 예상 | 새 유료 요청 차단/경고, 제공처·기한·남은 양·필요 조치를 통지 |
| 필수 수집 최종 실패·불완전 PM/AM·X 부분 성공/응답 불명 | 해당 편성 보류/중단, 결과 대조를 요구하는 알림 |
| 정상 0건·개별 기사 근거 부족·일반 목록/승인 성공 | DB/화면에 기록하고 푸시 알림 생략 |
| 같은 장애 반복·복구 | 같은 fingerprint는 열린 장애 동안 추가 알림 억제, 확인된 복구는 1회 |

429만으로 일일 요금제 소진을 단정하지 않는다. 제공처 응답·잔여 헤더로 단기 rate limit과 일일 quota/credit 부족을 구분한다. 단기 오류는 제한된 대기/재시도를 적용하고 최종 편성 보류가 필요할 때 알린다.

- outbound `sendMessage`만 사용한다. 운영자 chat 하나, 일반 텍스트로 환경·심각도·run/job ID·원인 코드·중단 여부·인증된 관리자 URL을 보낸다. 키/원문/전체 HTTP 오류는 보내지 않는다. `allow_paid_broadcast=false`를 유지한다. [Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage)
- 이벤트 저장과 중단 결정을 먼저 한다. Telegram 성공이 발행 허가를 뜻하지 않으며 알림 실패로 차단을 해제하지 않는다. Telegram으로 승인·복구·예산 변경 명령을 받지 않는다.
- DB에 기록할 수 없는 장애는 X 발행부터 차단하고 비밀을 제외한 표준 오류 로그와 Telegram 최선 노력 1회로 남긴다. 이 경우 영속 중복 억제는 보장하지 못하며 DB 복구 후 대조 기록한다.
- 발신은 총 최대 3회 시도하고 결과를 기록한다. 429의 `retry_after`를 존중해 다음 시도 시각을 예약하며 긴 대기는 다음 worker tick으로 넘긴다. timeout은 중복 수신 가능성이 있어 알림도 exactly-once를 보장하지 않는다. 실패 outbox는 대시보드에 남긴다. [Telegram 재시도 정보](https://core.telegram.org/bots/api#responseparameters)
- outbox는 새 이벤트 저장·worker 재시작·기록한 다음 재시도 시각에 처리한다. 예약을 복원할 때 이미 보낸 알림은 다시 추가하지 않는다. 알림을 위해 24시간 DB를 1분마다 조회하는 별도 루프는 만들지 않는다.
- VM/worker 전체가 멈추면 자체 봇도 발송할 수 없다. 외부 생존 감시·독립 경보는 MVP 이후이며 이번 알림의 감시 범위를 과장하지 않는다.

## 인수 시험

| 영역 | 최소 검증 |
| --- | --- |
| API·React | 미인증401·비허용403·CSRF·버전경쟁409, 목록→상세→승인/보류·새로고침·로딩/빈 결과/오류. OpenAPI/TS 타입 불일치 확인 |
| DB | 실제 임시 PostgreSQL에서 migration·유일 키·두 경쟁 승인/worker 점유. SQLite mock 결과로 PostgreSQL 원자성을 대신하지 않음 |
| AM·PM | AM 0/1/2기사·지수 누락/partial; PM 0/1/2/3후보·아침 중복·부분 수집·17:30 뒤 기사 제외·18:00 전 미전송·18:10 이후 차단 |
| X·비용 | 길이 공식 규칙·출처·수치/단위·한도·예산, timeout/재시작/중복 호출·부분 성공·unknown에서 중복 전송 금지 |
| Telegram | 민감 값 제거·fingerprint 억제·경고/중단 순서·429/timeout/3회 실패·DB 불가시 발행 차단/최선 노력·복구 1회. 실제 전송 시험은 사용자 승인 범위에서 별도 수행 |
| AWS·운영 | Linux 이미지 build·HTTPS·Google callback·healthcheck·컨테이너 재시작·정시 실행·메모리·사용량·허용 자료 백업/복원·이미지 태그 복귀 |

Python pytest/Ruff, React TypeScript build와 핵심 Playwright E2E를 CI에서 실행한다. 제품별 외부 호출은 mock이 기본이며 실제 호출과 발송은 키·권한·예산·사용자 승인 범위가 준비된 뒤 실행한다. 2주 완료는 reviewed MVP의 근거이고 5거래일/auto 운영 합격은 별도다.
