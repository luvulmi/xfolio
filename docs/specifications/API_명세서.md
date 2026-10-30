# 관리자 API 명세서

> 입력·편성의 단일 기준은 [현재 요구사항](../요구사항.md)이다. 현재 목표는 AM 최대 4글이며 기존 코드·OpenAPI·PM 이력/시험과 구분한다.
- 기준: 2026-10-31, Asia/Seoul
- 상태: **현행 0.1.0 대조 + 1단계 목표 계약**. 신규 경로/필드는 설계이며 아직 호출할 수 없다.
- 현행 기준: [app.py](../../src/xfolio/api/app.py) · [models.py](../../src/xfolio/api/models.py) · [store.py](../../src/xfolio/api/store.py) · [OpenAPI](../../contracts/openapi.json)
- 연결: [입력·검증 책임](뉴스_입력과_검증_책임.md) · [ERD](데이터_모델_ERD.md) · [IA](관리자_화면_구조.md)

## 읽는 순서와 상태

현행은 app/models/store와 OpenAPI snapshot이 기준이다. 아래 표와 본문의 `현행` 열만 현재 호출 계약이다. `목표 추가/강화`·`신규`는 초기 제품 설계, B01·SEC 등은 후속이며 공통 프로필·Exa 세부 필드는 미결정이다. [미결정 계약과 완료 조건](뉴스_입력과_검증_책임.md#미결정-계약과-결정-조건)을 먼저 확인한다. 관련 요구사항: FR-02~08,FR-10,NFR-01~04.

## 확정 범위와 구현 차이

뉴스 핵심은 **Exa+BLS CPI**, 가격 입력은 ETF `SPY/QQQ/DIA`다. 기존 10기업 우선+목록 밖 중요 사건을 검토한다. Fed·BEA·SEC 자동 수집과 CIK 필터는 후속이다. Exa 개발 채택·실측과 제품 어댑터/API 구현은 구분한다. [현재 요구사항](../요구사항.md)

**계약 확장 대기:** 아래 official 프로필·SEC 필드는 공식 자료용 목표 설계를 보존한 것이다. Exa에는 그대로 적용하지 않는다. N02/N08/N09에서 원매체·검색 조건·시각 정밀도·본문 절단·기사/보도자료·요청 비용·순위 상위 결과의 범위를 추가하고 프로필 식별자를 확정한다. 목표에서는 미등록 프로필을 차단하며 현행 전 경로 보장은 구현 인수에서 확인한다.

이 문서의 **현행 8경로**, **1단계 목표 10경로**, **B01 조회 확장 목표 13경로**를 구분한다. OpenAPI snapshot·DB schema·프론트 구현은 이번 명세 변경으로 바뀌지 않는다.

## 공통 규약

같은 HTTPS origin의 `/api`를 사용한다. GET 조회에는 세션 쿠키가 필요하며 POST에는 동일 origin의 `Origin`과 `X-CSRF-Token`도 필요하다. 쿠키·공급자 키·DB 비밀을 본문 예시나 로그에 남기지 않는다. 응답은 `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`다.

날짜는 KST 편성 대상일 `YYYY-MM-DD`, 시각은 UTC ISO8601로 직렬화한다. 미국 거래일은 별도 `market_trade_date`다. 서버가 입력 시각의 timezone을 검증하고 UTC로 정규화하는 것은 목표 계약이며 현행 일부 응답은 저장 offset을 그대로 직렬화할 수 있다. 클라이언트는 offset을 해석해 KST로 표시한다.

| 식별자 | 의미 |
| --- | --- |
| `id` in drafts/publications URL | **publication_jobs.id**, 편성의 안정 ID. content_drafts.id가 아님 |
| `version` | 해당 편성의 변경 불가 콘텐츠 버전 |
| `decision_revision` | 내용 변경 없이도 승인/보류마다 증가하는 결정 버전 |
| `content_hash` | 내부 원문 payload 해시. 승인 시 서버가 검증, 클라이언트가 정하지 않음 |
| `decision_id`, `attempt_id` | 각각 결정 감사·개별 외부 송신 시도의 ID |

현행 응답 DTO의 최상위는 `extra=forbid`이며 `publication/history/evidence/summary` 내부 일부는 dict이다. 이 문서에 정한 목표 세부 필드는 구현 시 Pydantic 타입·OpenAPI·TypeScript를 함께 갱신한다. 일반 서비스에 대한 배포 호환 약속은 없으며 UI/API를 같은 버전으로 배포한다. 현행 `contracts/openapi.json`에는 아직 목표 계약을 섞지 않는다.

## 인증

`xfolio_session`: Secure·HttpOnly·SameSite=Lax·Path=/api. 절대 만료12시간, 마지막 인증 요청 이후 유휴30분. `xfolio_oidc_flow`: Path=/api/auth·10분. OIDC state는 DB에서 한 번 소비하고 nonce/issuer/audience/만료/서명·허용 운영자를 확인한다. 운영자 허용 목록은 서버 설정이다.

| 메서드·경로 | 현행 요청 | 정상 응답 | 주된 실패 |
| --- | --- | --- | --- |
| GET `/api/auth/login` | 없음 | 307 Google 이동·flow 쿠키 설정 | 구성 불충분503, 저장소503 |
| GET `/api/auth/callback` | query `state`, `code` 필수 | 307 `/` 이동·세션 쿠키 설정 | 잘못된 state/검증/운영자403, query 형식422 |
| GET `/api/auth/me` | 세션 | 200 `Me` | 401/403/503 |
| POST `/api/auth/logout` | 세션·Origin·CSRF | 204, 세션 제거·쿠키 삭제 | 401/403/503 |

`Me`: `operator {email,display_name}`, `mode: dry_run|reviewed|auto`, `csrf_token`, `allowed_actions: string[]`. 현재 전역 allowed_actions는 reviewed에서 approve/hold, 그 외 hold다. 이것만으로 개별 편성 승인을 허용하지 않고 상세와 POST 검사 결과를 따른다. 로그인 공급자의 오류 callback 전용 UX는 현행에 별도 정의돼 있지 않으며 `code`가 없으면 형식 오류가 발생할 수 있다.

## 1단계 endpoint 목록

| 메서드·경로 | 상태 | 용도·WBS |
| --- | --- | --- |
| GET `/api/auth/login` | 구현 | 인증 시작 |
| GET `/api/auth/callback` | 구현 | 인증 완료 |
| GET `/api/auth/me` | 구현 | 세션·CSRF |
| POST `/api/auth/logout` | 구현 | 로그아웃 |
| GET `/api/drafts` | 구현·요약 보완 | 검토 목록 A02 |
| GET `/api/drafts/{id}` | 구현·근거/사람검토 확장 | 검토 상세 A02/A04 |
| POST `/api/drafts/{id}/decision` | 구현·확인 항목 추가 | 전체 승인/보류 A02/A04 |
| GET `/api/operations/summary` | 구현·날짜별 요약 확장 | 대시보드 A02/A03 |
| GET `/api/publications` | **신규 설계** | 시도된 편성의 발행 목록 A03 |
| GET `/api/publications/{id}` | **신규 설계** | 글별 송신·결정 이력 A03/A06 |

1단계 목표는 총10경로다. B01의 수집 목록/상세·설정 조회 3경로는 아래 목표 계약을 따른다. 운영 상세의 추가 endpoint는 실제 화면 요구에 따라 별도 명세하며 13경로 합계에 포함하지 않는다. 브라우저 수집/생성 실행·문안 수정·모드 변경·직접 게시·복구 endpoint를 추가하지 않는다.

## 검토 목록 · GET /api/drafts

| query | 타입·기본값 | 규칙 |
| --- | --- | --- |
| date | date 또는 생략 | KST 대상일. 생략 시 전체 |
| edition | AM/PM 또는 생략 | PM은 기존 이력 조회 전용. 신규 생성/승인/예약/송신 차단 |
| status | Status 또는 생략 | 아래 편성 상태 열거 |
| limit | int, 기본20 | 1~50 |
| cursor | 불투명 문자열 | 1시간 유효 서명 cursor, date/edition/status와 결합 |

정렬은 `target_date DESC, edition ASC, id ASC`다. 필터 변경 시 cursor를 버린다. tampered/expired/다른 필터 cursor는422 `CURSOR_INVALID`다. 현행 cursor는 limit와 결합하지 않으므로 페이지 크기 변경은 허용한다. 빈 items는 수집 성공이나 정상0건을 의미하지 않는다.

200은 `DraftList {items: DraftSummary[], next_cursor: string|null}`. DraftSummary 필드는 아래와 같다.

| 현행 필드 | 타입 |
| --- | --- |
| id | string |
| target_date / market_trade_date | date / date|null |
| edition | AM/PM |
| version / decision_revision | integer |
| status | Status |
| news_count | integer |
| scheduled_at / expires_at | datetime |

목표 추가는 `hold_reason: string|null`, `data_origin`, `transport_mode`다. 현행 목록 DTO에는 hold_reason이 없고 상세에만 있다. UI가 목록에서 보류 사유를 표시하려면 DTO/응답을 함께 확장해야 한다.

공식 발표/공시 목표에서는 `source_ids: SourceId[]`, `event_types: EventType[]`, `watchlist_version: string|null`도 요약에 추가한다. 목표 query `source_id`, `event_type`, `cik`는 편성에 해당 근거/사건이 하나 이상 있으면 일치한다. `cik`는 SEC의 10자리 숫자 문자열로 정규화하고 숫자형으로 직렬화하지 않는다. 새 필터는 서명 cursor에 결합하고 현행 API 지원으로 표시하지 않는다. 공급자 자료를 직접 브라우저에서 조회하지 않는다.

`Status = prepared|validated|approved|scheduled|sending|published|held|failed|partial|unknown|expired`. `no_content/not_operating`은 실행 결과이며 이 편성 상태 열거에 넣지 않는다. 목표 AM은 뉴스 0건이어도 ETF job이 있고 비운영일에는 job을 만들지 않는다. PM 상태는 목표에서 기존 이력 해석에만 사용하며 현행 신규 PM 처리 차단은 아직 구현 전이다.

## 검토 상세 · GET /api/drafts/{id}

현행200 `DraftDetail`은 DraftSummary에 아래 항목을 더한다. 존재하지 않는 job은404 `NOT_FOUND`다.

| 현행 필드 | 타입·현재 동작 |
| --- | --- |
| mode / synthetic | 모드 enum / boolean |
| validation | `{status:string, blocking_reasons:string[]}` |
| frozen_at | datetime|null |
| posts | `Post[]`, 순서·kind(index/news)·text·weighted_length·evidence_ids·evidence·event_key·fact_version |
| allowed_actions | 문자열 배열. 현재 상태/모드/synthetic 중심 힌트이며 기한·전체 검증 결과를 모두 반영하지는 않음 |
| publication | `{job_id, posts:[{position,state,x_id}]}` |
| history | 현행 store는 항상 빈 배열. 감사 조회 완료로 표시하지 않음 |
| hold_reason | string|null |

현행 `posts[].evidence[]`는 권한 플래그가 있는 저장 근거에서 id/source/url/published_at/collected_at/text/claims/event_key/fact_version을 투영한다. 전체 원문·이용 검토 내부 문서·세션·토큰은 공개하지 않는다.

1단계 목표 추가/강화:

- `data_origin: permitted_fixture|synthetic_fixture|live_capture`, `transport_mode: mock|live`, `generation_mode: mock|live`를 별도 표시한다.
- 공식 자료 전용 보존안 `validation.profile=official_news_reviewed_v1`, `assembly_profile=am_official_reviewed_v1`은 Exa 공통 목표의 확정 식별자가 아니다. 공통 프로필 식별자는 [미결정 계약](뉴스_입력과_검증_책임.md#미결정-계약과-결정-조건)에서 결정하며, `validation.checks[{code,status,message}]`, `validation.human_review_required=true`를 목표로 추가하고 기계 검사와 의미 검토를 구분한다. 이전 reviewed_news_v1/am_reviewed_v1 설계 이름을 새 공식 자료 profile의 구현 완료로 간주하지 않는다.
- `review_requirements: [evidence_support,conditions_preserved,relevance_and_novelty]`; `human_review: {status:pending|approved, operator:string|null, reviewed_at:datetime|null, version:int|null}`는 현재 유효 결정으로 계산한다.
- 각 post에 `claim_links[{claim_id,text_ko,evidence_id,evidence_position}]`, `selection_reason`, `index_relation`을 추가한다. 읽기 전용이며 서버의 검토된 입력으로 작성한다.
- 기존 `index_relation`을 ETF 가격과 혼용하지 않는다. 뉴스의 미국 시장·업종 관련성 필드와 ETF snapshot(SPY/QQQ/DIA, USD, 같은 완료 거래일)의 계약을 M01/N02에서 확정한다. 현재 두 지수 데이터로 ETF 완주를 표시하지 않는다.
- 뉴스 evidence에는 아래 `SourceEvidence` 메타데이터를 포함한다. SEC는 CIK·accession·form·item과 해당 첨부 근거를 보여 주며, 접수 사실만으로 실적/M&A 주장의 근거 검토를 대체하지 않는다.
- `history`는 ERD의 감사 이벤트에서 편성에 허용된 항목만 시간순으로 투영한다. 보류 사유·오류는 민감 값 제거 후 반환한다.
- `allowed_actions`는 현재 기한·첫 전송 여부·검증 상태를 반영하도록 보완한다. 사용자가 오래된 화면을 볼 수 있으므로 POST에서 항상 다시 검사한다.

### SourceEvidence · 목표 공통 계약

`SourceId = exa|bls|fed|bea|sec` (핵심 exa/bls, 후속 fed/bea/sec), `EventType = earnings|merger_acquisition|policy|economic_indicator`다. 아래 필드는 원천 근거 버전의 메타데이터다. 편성의 `content_hash`와 source evidence의 `content_hash`는 서로 다른 대상을 해시하므로 응답에서 각각의 객체 내부에 둔다.

| 필드 | 목표 규칙 |
| --- | --- |
| source_id / source_record_id | 제공처 enum(핵심 exa/bls, 후속 fed/bea/sec) / 제공처 안의 안정적인 레코드 식별자. URL·사건 ID와 구분 |
| url / title | 허용된 기사·발표 원문 URL / 원천 제목 |
| published_at | UTC datetime 또는 null. 원천에 확인되는 발행 시각만 저장하며 날짜만 있으면 시각을 지어내지 않음 |
| accepted_at | UTC datetime 또는 null. SEC 접수 시각이며 발행·최초 발견 시각으로 대체하지 않음. 비SEC는 null |
| retrieved_at | 이 근거 버전의 최초 조회 완료 UTC 시각. 같은 버전 재확인 시 덮어쓰지 않음 |
| available_at | 이 버전을 시스템이 실제 확보해 사용할 수 있게 된 최초 UTC 시각. `retrieved_at`보다 이르지 않으며 과거 발표 시각으로 역산 금지 |
| last_checked_at | 같은 버전을 마지막으로 재확인한 UTC 시각. retrieved_at/available_at과 별개로 갱신 |
| content_hash / source_revision | 근거 내용 해시 / 원천 정정·개정 식별자. 원천 값이 없으면 해시 기반 내부 버전임을 명시 |
| event_type / target_period | 사건 유형 / 사실의 대상 기간. 기간이 없는 정책/M&A는 target_period=null 가능 |
| cik / accession_number / form / item | SEC 메타데이터, 해당하지 않거나 확인하지 못한 값은 null. 필수 식별자가 없는 공시는 검토 보류 |
| evidence_refs | `{evidence_id, claim_id, locator, source_revision}` 배열. 표·문단·첨부 위치와 주장 연결, 본문 전체 전송은 아님 |
| rights_status | `permitted|pending_review|restricted|expired`. 근거 자료별 판단이며 SEC 공시라는 이유만으로 permitted 부여 금지 |

편성 cutoff는 `available_at <= cutoff_at`인 버전만 사용한다. cutoff 이전 발표/접수라도 이후 확보한 버전은 소급 편성하지 않는다. `published_at=null`을 `accepted_at`이나 자정으로 채우지 않고 원천 날짜·시간 정밀도는 별도 수집 메타데이터로 보존한다. 출처 정정은 새 버전과 재검토로 처리한다.

published_at과 accepted_at 모두 신뢰할 수 없으면 후보를 보류한다. 공식 자료의 지원 설계는 핵심 BLS CPI와 후속 Fed FOMC·BEA PCE·SEC8-K의2.02·1.01·2.01과 관련9.01 첨부를 통한 실적/M&A다. EX-99.1이나 item 번호만으로 사건과 주장을 확정하지 않는다. 고용·GDP·6-K/외국기업은 후속 범위다.

## 전체 결정 · POST /api/drafts/{id}/decision

필수 헤더: 세션 쿠키·`Origin`·`X-CSRF-Token`·`Idempotency-Key`(1~128자). 본문은 추가 필드를 거절한다.

| 필드 | 현행 | 목표 변경 |
| --- | --- | --- |
| action | approve/hold | 유지 |
| expected_version | integer ≥1 | 유지 |
| expected_decision_revision | integer ≥0 | 유지 |
| reason | 1~300자 또는 null, hold에 필수·공백 불가 | 유지. 저장/응답 전 민감 값 제거 추가 필요 |
| review_checks | **현행에는 없음** | `string[]`, approve 시 아래 3개를 중복 없이 정확히 요구. hold는 생략 또는 빈 배열 |

목표 승인 예시(가상 ID/버전, 실행 권한이나 실제 승인 아님):

```json
{
  "action": "approve",
  "expected_version": 3,
  "expected_decision_revision": 0,
  "review_checks": ["evidence_support", "conditions_preserved", "relevance_and_novelty"]
}
```

현행에도 맞는 보류 예시:

```json
{
  "action": "hold",
  "expected_version": 3,
  "expected_decision_revision": 1,
  "reason": "발표 조건과 문안의 표현을 다시 확인해야 함"
}
```

목표에서는 체크 누락/중복/불명 항목을422 `REQUEST_VALIDATION_FAILED`로 처리한다. 이것은 형식·명시적 확인 기록이며 서버가 의미를 자동 증명하는 검사가 아니다. 실제 source/버전/기계 검사가 실패하면 체크가 모두 있어도409로 차단한다. 기존 클라이언트의 승인 본문에는 새 필드가 없으므로 UI와 API를 같이 갱신한다. 설계 예시의 승인 본문을 현행에 보내면422다.

트랜잭션 처리 순서는 다음과 같다.

1. 인증·CSRF 확인 후 계정/월 비용을 보호하는 잠금과 job 행 잠금을 획득한다. 현행은 전역 advisory lock과 job 행 lock을 사용한다.
2. `(운영자, job_id, Idempotency-Key)`의 기존 요청을 조회한다. 같은 키/다른 본문은409, 같은 본문은 기존 결과+현재 상태를 반환하며 다시 승인하지 않는다.
3. 현재 콘텐츠 버전/revision과 비교한다. approve는 reviewed·비합성·validated·기한·최초 시도 전 조건을 확인한다.
4. 목표에서는 허용된 assembly/validation profile만 받는다. 저장된 근거/권한/수집/ETF/문안/길이와 새 `review_checks`를 검증한다. 현행은 CPI PM만 전용 재검증하고 그 외는 공통 플래그/구조 검사가 중심이다.
5. 편성 전체 한도·비용·사건 claim을 원자적으로 예약한다. job을 scheduled로 바꾸고 승인 감사 기록을 저장한다. 전체 필요량이 없으면 부분 승인하지 않는다.
6. hold는 첫 전송 전 예약/claim 해제 후 held, 첫 전송 후 stop_requested로 잔여만 중단한다. 이미 전송한 요청을 취소하지 않는다. 버전·결정 이력은 유지한다.

200 `DecisionResult`:

```json
{
  "decision_id": "demo-decision-1",
  "applied": true,
  "replayed": false,
  "version": 3,
  "decision_revision": 1,
  "status": "scheduled",
  "original_result": null
}
```

같은 요청 재전송은 `applied=false, replayed=true`, `original_result`는 최초 결과다. `version/revision/status`는 **현재 값**이므로 approve→hold→과거 approve 재전송이 재승인을 만들지 않는다. 멱등 키는 같은 재시도에서 유지하고 사용자의 새 결정에는 새 키를 쓴다. 승인 요청 timeout은 먼저 상세를 재조회하며 실제 X 송신 재시도와 혼동하지 않는다.

## 운영 요약 · GET /api/operations/summary

현행 query 없음, 200은 `collection/usage/publications/alerts` 네 객체다. collection은 가장 최근 run 하나, usage는 KST 현재 월의 estimated/reserved/confirmed와 상한50,000원, publications는 **전체 기간** published/held/unknown 개수, alerts는 `not_implemented`다. 이를 오늘의 편성·정상 알림0건으로 표시하지 않는다.

목표 query `date`(생략 시 KST 오늘)를 추가하고 다음을 기존 객체와 함께 반환한다.

| 목표 필드 | 규칙 |
| --- | --- |
| target_date / observed_at | 조회 대상일 / 서버 실제 조회UTC |
| editions[] | 활성 편성 AM만 반환. availability=`connected|not_connected`, result=`not_observed|not_operating|no_content|has_job`, job_id/status/target/expiry. PM은 과거 발행 조회에서만 표시 |
| publications | 대상일 집계로 전환, observed_at 명시 |
| usage | 기존 월 원장 합계·month·기준/관측시각, 실청구액이 아님 |
| alerts | 1단계 not_implemented 유지; 실제로 연결한 뒤 값 제공 |
| collection.sources[] | 핵심 exa/bls, 후속 fed/bea/sec별 scope·마지막 성공 시각·실행 ID·상태. Exa는 설정 질의/조회창/결과 상한/필수 요청·본문 확보 결과, 공식 자료는 해당 페이지/기업 완료 구간·watchlist_version을 투영. 연결 전은 not_connected, 실행 전은 not_observed |
| collection.market | required_symbols=`["SPY","QQQ","DIA"]`, completed_symbols, market_trade_date, status. 하나라도 빠지면 세 ETF 완료 아님 |

PM은 새 운영 요약에서 활성/연결 대기로 반환하지 않는다. API·프론트를 함께 갱신하고 기존 PM 이력 조회와 신규 승인/송신 차단을 별도로 검증한다.

제공처별 수집 상태는 `running|complete|partial|failed`이며 summary에서만 미연결/미실행을 `not_connected|not_observed`로 구분한다. `no_updates: boolean`은 `status=complete && new_version_count=0`일 때만 true인 파생 필드다. 별도 저장 status가 아니며 설정된 필수 요청 범위를 완료했으나 새 버전이 없다는 뜻이다. Exa는 질의·기간·상한과 필수 본문 요청의 완료이며 시장 전체 포괄이나 기관별 페이지/기업 완주를 뜻하지 않는다. 뉴스 선정0건과는 다르다. 페이지 미완료·관찰 기업 누락·제한에 걸린 수집은 partial이다. 마지막 한 기관의 성공으로 모든 기관 완주를 덮어쓰지 않는다.

후보의 게시 적격 여부는 별도 `eligibility: eligible|held|excluded`와 `eligibility_reasons`로 제공한다. rights_status가 pending_review/restricted/expired인 후보는 게시 적격이 아니지만 수집 실행 자체가 성공했다면 그 run을 failed로 바꾸지 않는다.

## 수집·관찰 목록 조회 · B01 신규 목표

| 경로 | 요청 | 응답의 핵심 |
| --- | --- | --- |
| GET `/api/collections` | date(KST 실행일), source_id, status, limit(기본20/최대50), cursor | `items: CollectionSummary[]`, next_cursor, observed_at |
| GET `/api/collections/{id}` | 수집 실행 ID | 요약 + scope·cursor_before/after·페이지/기업 완료 근거·근거 메타데이터·안전한 오류 |
| GET `/api/settings` | 없음 | 운영 모드·편성 시각·세 ETF 설정·기관별 활성/연결 상태·관찰 기업 목록과 버전, 비밀 없음 |

`CollectionSummary`는 `id, source_id, started_at, finished_at|null, window_start, window_end, scope, status, no_updates, watchlist_version|null, discovered_count, new_version_count, selected_count`를 포함한다. 수집 API의 status는 `running|complete|partial|failed`이며 no_updates는 위 식으로 계산하는 boolean이다. 미연결/미실행은 summary/settings에서만 표시한다. 근거 메타데이터가 아직 없으면 빈 배열과 수집 상태를 함께 반환한다.

collection 목록은 `started_at DESC, id ASC`로 정렬하고 1시간 서명 cursor를 전체 필터와 결합한다. 상세의 근거 목록도 기본20/최대50·서명 cursor로 페이지 처리하며 실행 정보는 반복 반환한다. 수집 공급자의 원시 cursor·응답·인증 값은 브라우저에 노출하지 않고, API용 안전한 진도 요약으로 투영한다. 외부 rate limit이나 일시 장애를 정상0건으로 반환하지 않는다.

`settings.watchlist`는 `version, effective_at, company_count, companies[{cik,tickers,name,enabled}], max_companies=10`의 읽기 전용 객체다. 목표는 10개이며 명단 교체는 새 버전으로 기록한다. 공식 법인명·CIK·감시 시작일이 미검증이면 설정 완료로 표시하지 않는다. ticker는 변경 가능하므로 기업 식별의 기준은 CIK다. 과거 수집에는 당시 watchlist_version과 대상 CIK 집합을 보존한다. 브라우저의 임의 목록 변경 endpoint는 없다.

모든 신규 조회는 기존 세션·no-store 규칙을 따르고 401/403/404/422/503 오류 계약을 재사용한다. 이 3경로는 현재 OpenAPI에 없으며 신규 시험과 구현 후에만 이용할 수 있다.

## 발행 목록 · GET /api/publications · 신규

query는 drafts와 같은 `date/edition/limit/cursor`, 추가 `transport_mode=mock|live`, `status=sending|published|partial|unknown|failed`다. **first_attempt_at이 존재하는 편성만** 조회한다. 예약 대기·전송 전 보류는 검토 목록에 남는다. 날짜는 요청일이나 첫 송신일이 아닌 KST 대상일이다.

정렬 `target_date DESC, edition ASC, id ASC`, 기본20/최대50. 1시간 서명 cursor는 모든 필터와 결합하며 다른 endpoint cursor를 허용하지 않는다. 인증·권한·형식 오류는 공통 규칙을 따른다.

200 `PublicationList {items: PublicationSummary[], next_cursor:string|null, observed_at:datetime}`:

| PublicationSummary 필드 | 타입·규칙 |
| --- | --- |
| id / target_date / edition / version | job 식별자·편성일·AM/PM·처음 송신한 불변 버전 |
| status | 위 발행 상태 |
| data_origin / transport_mode | 입력 출처 / 송신 방식 별도 |
| first_attempt_at / last_updated_at | UTC datetime |
| total_posts / published_posts / unknown_posts / failed_posts | integer ≥0, 총 글 수 기준. 예약/미시도 글은 성공으로 세지 않음 |
| stop_requested | boolean, 잔여 중단 상태 |

mock의 state가 published여도 UI는 “모의 전송 완료”로 표시한다. API/UI는 결과를 data_origin만으로 추정하지 않는다. 사건·게시물 중복 방지는 조회 필터가 아니라 DB/worker의 책임이다.

## 발행 상세 · GET /api/publications/{id} · 신규

존재하지 않거나 아직 first_attempt_at이 없는 job은404 `NOT_FOUND`다. 200은 PublicationSummary에 `posts[]`, `history[]`, `next_action`을 추가한다.

| 목표 구조 | 필드 |
| --- | --- |
| posts[] | position, kind, text, state(reserved/sending/published/failed/unknown/cancelled), x_id|null, x_url|null, attempts[] |
| attempts[] | attempt_id, started_at, finished_at|null, outcome(sending/published/failed/unknown), error_code|null |
| history[] | event_id, type, occurred_at, actor(operator/worker), version, decision_revision|null, safe_reason|null |
| next_action | none / await_result / reconcile_result / inspect_failure |

글은 position 순서, 시도·감사는 발생 시각과 ID로 안정 정렬한다. mock이면 x_id/x_url은 null이다. live의 URL은 확인된 X ID와 검증한 대상 계정에서 서버가 만든다. 전체 외부 응답·세션·비밀·기사 전문은 반환하지 않는다. partial/unknown에는 재게시 API나 버튼을 제공하지 않는다.

## 오류 계약과 차이

현행 도메인 오류는 다음 형식이며 메시지는 일반화돼 있다.

```json
{"error":{"code":"VERSION_CONFLICT","message":"요청을 처리할 수 없습니다. 최신 상태를 확인하세요."}}
```

| HTTP | 현행 코드·상황 |
| --- | --- |
| 401 | AUTH_REQUIRED |
| 403 | OPERATOR_FORBIDDEN, CSRF_FAILED, OIDC_STATE_INVALID, OIDC_VERIFICATION_FAILED, AUTH_FAILED |
| 404 | NOT_FOUND |
| 409 | VERSION_CONFLICT, DECISION_CONFLICT, IDEMPOTENCY_CONFLICT, MODE_BLOCKED, VALIDATION_BLOCKED, TRANSMISSION_STARTED, DEADLINE_PASSED, DUPLICATE_EVENT, QUOTA_BLOCKED, BUDGET_BLOCKED |
| 422 | CURSOR_INVALID 또는 FastAPI/Pydantic 기본 `detail` 형식 |
| 503 | CONFIGURATION_REQUIRED, STORAGE_UNAVAILABLE |

목표는 422도 `error {code,message,fields?}`로 통일한다. fields는 경로와 안정적인 사유 코드만 담고 원래 입력/기사/토큰을 반사하지 않는다. `VALIDATION_BLOCKED`일 때 상세의 허용된 blocking_reasons를 다시 읽는다. 현행 저장 reason은 민감 값 제거가 보장되지 않으므로 A02/A04에서 마스킹·출력 검사를 추가한다.

현재 OpenAPI에는 수동 쿠키/CSRF 인증과 모든 도메인 오류가 완전히 표현되지 않는다. 구현 시 cookie security scheme·헤더·도메인 응답·타입을 명시하고 snapshot을 갱신한다. 새 목표 경로가 구현되기 전까지 기존 `8개 경로` 시험은 현행 검증으로 유지하며, 실제 확장 시 `10개 경로와 계약 일치` 검증으로 변경한다.

## 구현 인계

| 담당 | 변경 |
| --- | --- |
| A02 | review_checks UI/승인 본문·검증, 상세 사람 검토 표시, DTO/오류/summary 의미·OpenAPI/TS 일치 |
| A03 | publications 2조회 API·페이지 규약·안전한 이력 투영 |
| A04 | 일반 AM/뉴스 profile·검사 재호출·승인 감사 저장, 미등록 profile 차단 |
| A05/A06 | 원자적 점유·전송 전 시도 기록·결과/비용·mode 표기와 이력 |

이번 산출물은 명세다. 현재 8API·OpenAPI 파일과 제품 코드는 수정하지 않았다. 핵심 Exa/BLS·세 ETF·공통 source evidence는 초기 확장 대상이며 Fed·BEA·SEC 자동 수집과 B01 조회는 후속이다. 기존 BLS 전용 구현과 공통 AM 확장을 구분한다. 모든 실패 계약의 시험 방법은 [기존 관리자 검증](../../tasks/verification/admin/관리자_화면과_승인_API.md)과 구현 작업에서 관리한다.

## 아침 최대 4글 전환 계약

현행 store는 AM 글 수 1~3, DB reserved_count는 0~3, publication_posts.position은 1~3이다. 목표는 ETF 첫 글+뉴스 0~3으로 전체 1~4글이며 5글·중복 사건·필수 ETF 누락을 거절한다. reserved_count 0~4·position 1~4의 신규 migration과 API/편성/worker의 글 수·한도 검사를 함께 변경한다. PM은 조회만 허용하고 생성·승인·예약·송신을 차단한다. 과거 PM reservation은 전송 없이 보류하며 감사 이력을 남긴다. 이 문서 작업에서는 코드를 변경하지 않았다.
