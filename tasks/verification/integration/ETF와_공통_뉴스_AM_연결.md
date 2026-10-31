# ETF와 공통 뉴스 AM 연결

- 기준: 2026-10-31, Asia/Seoul
- 상태: 구현·격리 인수 완료. [계획](../../plans/ETF_수집.md) · [수행 기록](../../logs/2026-10-31_ETF와_AM_승인_연결.md) · [뉴스 입력](../news/뉴스_공통_입력_계약.md) · [수집·검사](../news/Exa와_BLS_어댑터_근거_검사.md)

## M01

제품 가격 입력은 SPY·QQQ·DIA USD ETF다. legacy IndexClose/MarketSnapshot/market-close는 기존 지수 호환을 위해 유지하고 ETF 전용 모델·etf-close를 추가한다. yfinance 동일 Ticker의 history(auto_adjust=false/back_adjust=false/repair=false/actions=true)와 metadata.currency/instrumentType을 대조한다. 세 ETF와 이전 Close가 같은 완료 거래일 쌍이어야 하며 달력·오래된/중복/미완료/통화 오류·누락은 전체 실패다.

원본 Close 대비 가격 등락률을 계산한다. 분배금은 기록하고 총수익률로 합산하지 않는다. 두 관측 거래일의 분할은 별도 대조가 필요해 자동 편성을 보류한다. 같은 거래일 snapshot의 종가 수정은 이전 hash와 관계를 남기고 자동 재사용을 보류한다. UTC 확보 시각·미국 거래일·출처·통화를 보존하며 완성 ETF 글은 'USD, 분배금 미포함'을 표시한다.

## A01

0001의 현재 metadata 참조를 당시 8테이블 DDL snapshot으로 고정한다. 기존 적용 DB DDL을 바꾸지 않으며 새 0002에서 reserved_count 0~4·post position 1~4만 확장한다. 신규/0001→head·downgrade/재upgrade를 격리 DB에서 검사한다. running 수집 저장은 이번 migration에 넣지 않는다.

새 kind=etf를 API/화면에 추가하고 legacy index/PM 조회는 유지한다. 새 PM 생성·approve는 PM_DISABLED로 거절하며 hold/기존 멱등 결정 조회는 유지한다. 새 AM은 미등록/legacy assembly profile을 승인하지 않는다. 새 승인 요청에는 evidence_support/conditions_preserved/relevance_and_novelty 세 true 확인을 요구하고 운영자·시각·내용 hash·버전·수집/근거 버전에 묶어 감사한다. UI에서 세 항목을 확인하고 전송하며 새 버전/재조회 실패 때 확인을 무효화한다.

## A04

프로필은 am_etf_news_v1, 기계 검사는 etf_news_review_v1이다. 필수 exa/bls 각각의 공통 collection과 ETF snapshot을 저장하고, 실제 연결한 run/status/hash를 생성과 승인 때 재검사한다. complete은 제공처별 bounded scope이며 시장 전체 포괄이 아니다. partial/failed·누락을 뉴스 0건으로 대체하지 않는다. 전체 입력은 07:30 KST까지 확보하고 같은 날짜 08:00 예약·09:00 신규 전송 마감이다. 새 완료 거래일이 없으면 job을 만들지 않는다.

ETF 1글+서로 다른 사건의 뉴스 0~3글이며 전체 1~4글, 5글은 거절한다. 뉴스 body/claim_id 연결과 원문 URL은 분리하고 URL은 서버가 원문에서 조합한다. 외부 AI 생성은 이번에 추가하지 않으며 주어진 초안은 기계 검사와 사람 대조를 거쳐야 한다. 원문 hash·주장 수치/범위/기간/단위/전망·조건을 보존하고 본문/권리/시각/관련성·중복·정정을 공통 검사에 연결한다. 의미·관련성·새 사실 최종 대조는 사람이 한다. NFC ASCII/완성 한글의 제한된 길이 계산을 지원하고 URL은 23으로 세며 지원 밖 문자/이모지는 보류한다.

원문/이용 권리는 승인 시 새 DB 자료로 재확인한다. 저장은 collection/evidence/draft/job 경계를 하나의 트랜잭션으로 처리하고 원문 source_id는 provider:record_id로 매핑한다. 이미 기록한 run은 다른 payload로 덮어쓰지 않는다. synthetic fixture/모의 생성은 발행 승인 불가이며 legacy 자료가 새 계약 필드를 생략한 채 통과하지 못한다. X 송신·lease·worker는 A05/A06의 후속이다.

transport_mode는 기본 mock이다. 허용 fixture는 mock 예약으로만 인수하며 live는 snapshot과 모든 수집 원본이 live_capture여야 한다. synthetic 자료/모의 생성은 승인 예약 자체를 차단한다. 입력의 generation_mode=live·synthetic=false를 쓰는 성공 시험은 격리된 정상 경로의 전제이며 실제 공급자/AI 성공의 근거가 아니다.

`record_common_collection`은 본문 없이 수집 메타데이터를 저장하고 현재 예약/승인 근거를 대체하는 정정본을 발견하면 이전 job을 hold한다. 첫 전송 전 예약/비용은 해제하며 시작 후에는 stop_requested와 불명 claim/예약을 보존한다. 같은 run 재처리는 멱등이고 input_invalidated 감사에 원문 변경·run/job/version을 남긴다. 이 처리는 worker 송신 구현이나 외부 원문 자동 재조회가 아니다.

## 검증

외부 API 없는 ETF 응답·뉴스 fixture로 0/1/2/3건·5글 거절·시간 경계·부분 실패·권리/원문 변경·미등록 profile·PM 차단·legacy 조회를 검증한다. 격리 PostgreSQL에서 migration·4번째 위치 저장·5번째 거절·재승인/동시 승인/멱등·감사를 확인하고 API/OpenAPI/React build·검사를 대조한다. 운영 DB·실제 X에는 접근하지 않는다.

10/31 결과: 전체 Python 616 passed, skip0, 기존 Authlib 경고1건. 프론트 12개·실제 HTTPS/API/PG 브라우저 2개 통과, build·Ruff·OpenAPI 대조·문서 검사 통과. [4글 예약 화면](../assets/integration/2026-10-31_AM_4글_승인.png)은 가상 가격/기사와 모의 생성 전제를 둔 격리 시험이다. 실제 X 결과가 아니다.
