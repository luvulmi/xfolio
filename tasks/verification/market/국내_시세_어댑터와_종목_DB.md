# T02 · 국내 시세 어댑터·거래일·종목 DB

- 기준/수행: 2026-11-03, Asia/Seoul. 상태: **T02 구현/격리 시험 완료**. 전체761건·최종 T02 집중47건 통과. 운영 DB/정시 수신 인수와 구분한다.
- 선행: [T01](국내_ETF_API_표본_검증.md) 커밋 `6999dc7`. [계획](../../plans/국내_시세와_종목_DB.md) · [운영 정책](../../../docs/운영_정책.md).
- 확정: **가격90일**, 가격 없는 전송/설정 감사1년. 이전1년→30일 결정은 당시 로그로 보존하며 현재 운영 기준으로 사용하지 않는다.

## 모듈·기술 계약

| 경계 | 구현 | 인수 범위 |
| --- | --- | --- |
| 시세/결과 모델 | [models.py](../../../src/xfolio/domestic/models.py) | KRX/KRW·비수정 종가·Decimal·가격 기준일/실제 시각/조회시각·부분/전체 실패·내용 해시 |
| 인증/조회 | [kis.py](../../../src/xfolio/domestic/kis.py) | 실전 주소 고정·토큰 메모리 캐시/만료60초 전 갱신·프로세스 내 잠금·직렬1.1초·timeout20초·재시도0회·고정 오류 코드 |
| 거래일 | [calendar.py](../../../src/xfolio/domestic/calendar.py) | KIS `opnd_yn`14일 구간과 XKRX 개장/마감 대조·완료2일·HTTPS 근거의 특수 마감 override |
| 종목 | [catalogue.py](../../../src/xfolio/domestic/catalogue.py) | 공식 공개 KOSPI ZIP·CP949/228문자 후미·6자리 숫자 코드·국제 ISIN·정규화 코드/이름 검색 |
| DB 서비스 | [store.py](../../../src/xfolio/domestic/store.py) | 기본3종목·revision/순서·활성10개·버전/정정·90일 조회 차단/삭제·가격 없는 수집 이력 |
| DDL | [domestic.py](../../../src/xfolio/db/domestic.py) · [0003](../../../migrations/versions/0003_domestic_market.py) | 신규7개 테이블·DB 제약/trigger·기존0001/0002 및 AM/PM 보존 |
| 실행 | [CLI](../../../src/xfolio/domestic/cli.py) | `domestic-close`/`domestic-catalogue`/`domestic-prune`, 기본 무통신·DB쓰기0회, `--run` 명시 시만 실행 |

토큰은 동일 `KisClient` 안에서 재사용하며 여러 스레드의 발급/조회는 잠금으로 직렬화한다. 다른 프로세스·외부 앱의 계정 유량까지 통제한다고 주장하지 않는다. worker 단일 작업 점유/재시작 인수는 T06이다. DB 연결 시 휴장일 API는 날짜별 원자 점유/성공·실패 기록을 공유해 재시작해도 하루 중복 조회하지 않는다. 실제 휴장일GET 실패나 불완전 응답은 그날 확인 불가로 남기며 점유를 지워 자동 재호출하지 않는다. GET 이전의 인증 실패는 일일 점유를 소비하지 않아 새 자격정보/클라이언트로 복구할 수 있다.

달력에 오늘과 직전14일의 개장 여부가 없거나 KIS/XKRX가 다르면 전체 가격 수집을 보류한다. 공식 개장 flag만으로 특수 마감시각을 알아냈다고 주장하지 않는다. 별도 확인한 HTTPS 근거와 예정시각의 override를 제공하며 오후 실제 시각 인수는 T09다. 일봉은 날짜만 제공하므로 `price_as_of=null`, 달력 마감은 `scheduled_close`, 응답 확보는 `retrieved_at`로 구분한다.

## 원종가 변동률·락/분할 경계

- raw 변동률은 precision28의 Decimal `(latest/previous-1)*100`, 최종2자리 `ROUND_HALF_UP`이다. 수정주가0·NAV·분배금·공급자 전일대비율을 혼합하지 않는다.
- T02의 자동 비교 채택 조건은 **두 행의 T01 관측 필드 패턴 `00`/분할0/변경N/재평가 빈 값 + 최신 공급자 전일차액과 두 원종가의 직접 차액 일치**다. 이를 `basis_verified`로 검증한다. 이는 숫자 기준의 일관성 검사이며 `00`의 전체 enum 해독·분배락 없음·투자 총수익률을 뜻하지 않는다. 원종가 계산은 항상 분배금 미포함 가격 변동률이다.
- 이 조건이 다르거나 필드가 없으면 자동 발송용 등락률은 null이다. 확인된 별도 사건 근거로 `none`/`distribution`을 지정할 수 있고 분배락은 가격 변동률로만 계산한다. 분할/변경·미확인 비교는 보류한다. 매회 사람 승인을 요구하는 구조는 아니며, 별도 사건 근거 입력은 서버 내부 계약이고 관리자 UI/API는 T05다.
- T01 실표본을 새 모델로 재생하면 -1.36/-2.56/+0.20%와 숫자 기준이 일치한다. 실제 분배락/분할일을 새로 조회한 시험은 아니며 사건 처리 시험은 합성이다. 이 구분을 T07 실제 아침 인수에서 유지한다.

## DB 설계·동시성·90일

신규 테이블은 `domestic_instruments`, `domestic_watchlist`, `domestic_watchlist_versions`, `domestic_calendar_requests`, `domestic_calendar_days`, `domestic_market_runs`, `domestic_price_snapshots`다. legacy8개 metadata와 분리해 Alembic에서 두 집합을 연결하며0003은 [고정 DDL](../../../migrations/schema_0003.py)을 참조한다.

- 기본3종목은 사용자 확정 지원 범위와 T01 이름/ISIN/종가 근거로 활성화한다. 기타 종목은 검색 가능하되 `eligible=false`다. 이름/단일 마스터 플래그만으로 해외 ETF를 자동 확정하지 않으며 별도 지원 근거 검토 후 서버 서비스로 활성 적격을 확인한다.
- 관심목록은 순서 있는 코드 배열+revision으로 원자 교체한다. 행 잠금·기대 revision 검사, DB 길이1~10 CHECK·코드 중복/존재/eligible trigger·감사 버전 생성으로11번째 활성화와 오래된 덮어쓰기를 막는다. 활성 종목의 삭제/적격 해제도 DB가 막는다. 비활성화는 목록에서 제거하는 동작이고 카탈로그/과거 이력은 남긴다.
- 수집 시작 시 코드/순서/revision을 고정한다. 저장 시 해당 버전과 일치해야 하며 실패하면 수집 run/가격 전체를 rollback한다. 종목별 오류는 가격 없는 run 메타데이터에 보존하고 정상 가격만 저장한다.
- 동일 코드/거래일의 **최신 내용** 해시가 같으면 기존 가격 ID를 재사용하고 만료를 연장하지 않는다. 수치 표현 `25010`/`25010.0000`도 같은 내용이다. 정정 A→B→A는 각각 새 버전·`supersedes`로 연결한다. 오래된 조회 응답은 새 가격을 덮어쓰지 못한다. 정정 버전의 자동 발송용 등락률은 보류한다.
- 재사용 때에도 현재 관심목록 순서와 매회 정확한 조회시각·가격 ID를 `domestic_market_runs.observations`에 보존한다. 이 배열은 코드/불투명 ID/시각만 저장하며 가격을 복제하지 않는다. 이 JSON 참조는 SQL FK가 아니며90일 후 가격이 삭제돼도 가격 없는 수집 이력으로 남는다.
- `expires_at = first_stored_at + 2160 hours`로 정확한 UTC90일을 보장한다. DB 세션 시간대의 DST가 경과시간을 바꾸지 않는다. 만료 시점부터 조회에서 제외하고 명시적 삭제 서비스가 payload/가격 칼럼을 함께 제거한다. 상위 버전이 남은 경우 정리된 이전 버전 연결은 null로 바꾸되 나머지 값/만료시각은 불변이다.
- 이번 신규 run/설정 이력에는 가격을 복제하지 않는다. 앞으로 편성/발송 payload·캐시에 가격을 복제하면 같은 만료를 적용하며 백업 복원 후 만료 가격 제거/정기 삭제 예약은 T08이다. Telegram 대화 기록의 자동 삭제를 구현한 것은 아니다.

## 실제 근거와 합성 시험

- [공개 마스터 실제 파싱 요약](../assets/market/KIS_종목_마스터_2026-11-03/표본_요약.json): 전체2,580행→지원6자리1,772행·기타 식별자808행 제외, 기본3개 식별/검색/지원 일치. ZIP2회 조회 후 로컬 재생으로 수정 검증, 인증 시세 재조회0회. 외국 발행사 ISIN도 있으므로 `KR` 접두사만 강제하지 않는다. 수집본 전체를 Git에 복제하지 않았다.
- 가격은 [T01 실표본](../assets/market/kis_close_2026-11-03T225345459055KST/close_probe.json)을 무통신 재생한다. 신규 가격 API/Telegram 호출과 구분한다.
- [무통신 시험](../../../tests/market/test_domestic_market.py): 캐시/만료·동시 호출·휴장일/특수 마감·가격/사건 형식·오류/부분/전체 실패·비밀 비노출·공개 마스터·CLI 기본 무통신.
- [실제 PostgreSQL 시험](../../../tests/market/test_domestic_postgres.py): 무작위 별도 schema에서0003 upgrade/downgrade/re-upgrade, 기본/검색·미검증 추가 보류·동시10개/CAS·직접 SQL 우회 거절·중복/정정/되돌림·rollback·90일 경계·DST·이전 버전 정리·가격 없는 감사 보존·legacy 행 보존.

Docker Desktop 기동 중 사용자 PC의 `dockerInference` 런타임 오류가 발생했다. 사용자 재기동 후 엔진28.5.2와 기존 컨테이너 상태를 읽기 확인했다. 시험은 저장소의 기존 portable PostgreSQL loopback55432에서 했고 기존 Docker 컨테이너/운영 DB는 쓰지 않았다. 격리 시험 schema만 만들고 정리했다. [Docker 공식 동일 증상 보고](https://github.com/docker/desktop-feedback/issues/625).

[실제 결과와 최종 검증](../../logs/2026-11-03_국내_시세와_종목_DB_구현.md). T02 코드 존재를 AWS 운영·07:50 수집/08:00 수신·오후 슬롯 인수로 확대하지 않는다.
