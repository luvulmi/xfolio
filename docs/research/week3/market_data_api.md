# R1. 주가지수 API 조사

- 확인일: 2026-10-22, Asia/Seoul
- 범위: 공식 가격·API·이용 조건 페이지 검색 및 열람. 인증 API 호출·가입·결제·문의·X 게시 미실행.
- 기준: [조사계획서](../../../tasks/week3_research_plan.md), [설계](../../market_briefing_agent_design.md), [운영 추천안](../../market_briefing_operating_plan.md)

## 결론

**2026-10-23 사용자 확정: 지수 수집 수단은 yfinance다.** S&P 500 `^GSPC`·Nasdaq-100 `^NDX`의 일별 종가와 직전 거래일 값을 조회해 등락률을 계산한다. 상세는 [yfinance 채택 문서](yfinance_index_collection.md)를 따른다. 아래 FRED·FMP·Twelve Data·Alpha Vantage는 비교 이력이며 FRED 우선 후보 결론보다 이번 선택을 우선한다. 설치·실제 응답·오전 제공 시각·공개 게시 조건 검증은 미완료다.

2026-10-23 재확인: [FRED 공개 게시 조건·아침 제공 시각](fred_publication_and_timing.md)에 두 질문의 근거와 확인 한계를 모았다. 개인 SNS 일반 허용과 지수별 사전 승인 조건을 구분했으며, 공개 갱신 표시를 API 최초 수록 실측으로 취급하지 않는다. 공개 허가 취득과 오전 도착 시험은 여전히 미완료다.

표현 정정: **무료 API 조회 경로는 있다.** FRED의 무료 API와 정확한 두 계열이 확인됐으며 계정에서 키를 발급받아 응답을 시험할 수 있다. 아직 확보하지 못한 것은 공개 게시·보관 권한과 아침 목표 시각을 충족하는 운영 경로다. 이를 ‘무료 API 조회 자체가 어렵다’고 일반화하지 않는다. API 키·실제 응답 시험이 없으므로 운영 적합성이 확인된 것은 아니다.

권한을 별도로 재점검한 [공개 이용 권한 문서](public_usage_rights.md)에 최신 판단을 정리했다. Nasdaq EOD 성과에 GDA 요구의 제한적 예외가 있지만 종가 원값·공급 경로·기타 계약을 포괄 면제하지 않아 현재 구성은 별도 확인이 필요하다.

정확한 S&P500·Nasdaq-100 종가를 얻는 문서상 경로는 있지만, **월 3만 원 안에서 정기 X 게시 권한과 아침 도착 시각까지 확인한 제공처는 없다.** 조사 당시 FRED를 내부 개발 후보로 검토했으나 현재 구현 선택은 yfinance다. FMP와 Twelve Data도 대안 비교 이력으로 남긴다. 이는 모든 무료 경로가 불가능하다는 결론이 아니다.

종가는 가격지수의 같은 거래일 값으로 맞추며 Nasdaq Composite·SPY·QQQ·선물·총수익지수를 대체값으로 쓰지 않는다. 호출 성공·데이터 제공·공개 게시 허용을 각각 확인한다.

## 후보 비교

| 후보 | 자료와 접근 | 비용·제한 | 공개 게시 조건 | 난이도·현재 판단 |
| --- | --- | --- | --- | --- |
| FRED | `SP500`, `NASDAQ100` 일별 마감 계열. observations API에서 날짜·값 조회 | API 무료, 등록 키 필요. 안정적 운영 호출 한도는 별도 확인 | 두 계열 모두 `Copyrighted: Pre-Approval Required`. SP500 주석은 사전 서면 허가 요구 | REST/JSON은 단순. 권한·시간 때문에 공개 운영 보류 |
| Financial Modeling Prep(FMP) | Historical Index Full Chart에서 일별 OHLC. 공식 예시는 S&P500 `^GSPC`; Nasdaq-100의 정확한 심볼·요금제 접근은 미확인 | Basic $0·250 calls/day. Starter $19/월은 연 결제 환산값이며 월 결제 금액으로 쓰지 않음 | 가격 페이지에서 표시·재배포에 별도 Data Display and Licensing Agreement 요구 | REST 단순. 두 정확한 지수·최종 종가 시각·별도 권한/견적 전 채택 보류 |
| Twelve Data | 지수 포함 여부·정확한 두 지수 심볼·일별 확정 종가 접근을 샘플로 확인해야 함 | Business Basic: 무료, 8 API credits/min·800/day, internal non-display. 외부용 최종 가격은 견적 확인 | Individual은 개인/내부용. Business도 거래소 조건 적용, 재배포 별도 계약 | 무료 개인 요금제를 공개 X 운영에 사용한다고 가정할 수 없음. 확인 후보 |

근거: [FRED SP500](https://fred.stlouisfed.org/series/SP500), [NASDAQ100](https://fred.stlouisfed.org/series/NASDAQ100), [API 키](https://fred.stlouisfed.org/docs/api/api_key.html), [FRED 약관](https://fred.stlouisfed.org/legal/), [FMP 지수 문서](https://site.financialmodelingprep.com/developer/docs/stable/index-historical-price-eod-full), [FMP 가격](https://site.financialmodelingprep.com/developer/docs/pricing), [Twelve Data Business](https://twelvedata.com/pricing-business), [개인·상업 이용 구분](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage).

Twelve Data 가격 페이지는 선택형 크레딧 구성이다. 화면의 특정 금액을 두 지수의 X 게시 라이선스 총액으로 적용하지 않았다. FMP의 무료 EOD 기능 안내도 해당 두 심볼 무료 접근이나 게시 권한을 증명하지 않는다.

## FRED에서 직접 확인한 시간 제약

2026-10-21 거래일의 페이지 표시를 확인했다. 아래는 웹페이지의 마지막 갱신 표시를 KST로 환산한 사례이며, API 최초 수록 시각이나 매일의 보장 시각을 실측한 결과가 아니다.

| 계열 | 페이지 갱신 표시 | KST 환산 | 현재 아침 계획과의 관계 |
| --- | --- | --- | --- |
| SP500 | Oct 21, 2026 7:01 PM CDT | 10월 22일 09:01 | 08:00 목표·09:00 마감보다 늦은 표시 |
| NASDAQ100 | Oct 21, 2026 10:37 PM CDT | 10월 22일 12:37 | 08:00 목표·09:00 마감보다 늦은 표시 |

원문: [SP500 갱신 표시](https://fred.stlouisfed.org/series/SP500), [NASDAQ100 갱신 표시](https://fred.stlouisfed.org/series/NASDAQ100). CDT는 UTC−5, KST는 UTC+9로 14시간 차이다. 이 사례만으로 항상 늦게 도착한다고 단정하지 않지만, 07:30 준비와 08:00 발행을 보장하는 자료로 채택할 수 없다. 공개 권한을 해결해도 별도로 도착 시험이 필요하다.

## 구현에 사용할 데이터 형태

[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)는 `series_id`, `observation_start/end`, `sort_order`, `file_type=json`을 지원한다. 응답 관측값에는 `date`, `value`와 실시간 기준 필드가 있다. 아래는 요청 형태 설명이며 실제 호출 응답이 아니다.

```text
GET /fred/series/observations
  series_id=SP500 또는 NASDAQ100
  observation_start=<직전 값까지 포함하는 시작일>
  observation_end=<대상 미국 거래일>
  file_type=json
  api_key=<비밀 저장소의 등록 키>
```

내부 공통 필드는 `index_id`, `trade_date`, `close`, `previous_trade_date`, `previous_close`, `provider`, `source_url`, `retrieved_at`, `provider_updated_at`으로 둔다. 이는 구현 제안이며 제공처가 모든 필드를 직접 반환한다는 뜻이 아니다. 지수 값은 Decimal로 보존하고 `(close / previous_close - 1) × 100`으로 계산한다. 날짜가 없거나 결측이면 전일 값을 오늘 값으로 복사하지 않는다.

종가 확정 플래그·수정 이력·갱신 SLA는 각 제공처에서 미확인이다. 시리즈의 `realtime_start`를 장중 최초 공개 시각으로 해석하지 않는다.

## 거래일·마감 확인

[Nasdaq 공식 일정](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule)에서 2026년 휴장·조기 마감을 확인했다. 정규 주식 거래는 09:30~16:00 ET이며 11월 27일·12월 24일은 13:00 조기 마감으로 표시한다. 종가가 없는 날짜만 보고 휴장으로 단정하면 제공처 장애를 놓칠 수 있다.

거래소 공식 일정을 기준 자료로 보존하고 미국 현지 거래일을 계산한다. Python 거래일 라이브러리를 채택한다면 공식 일정과 대조하고 긴급 휴장 갱신을 확인한다. 라이브러리 설치·검증은 이번 조사에서 실행하지 않았다. 지수의 실제 확정·배포 시각은 정규장 종료 시각과 별도다.

## 비용 계산에 넘길 값

- 정상 호출량 가정: 운영일당 두 계열 각 1회 = 2회. 22일 가정이면 월 44회이며 재조회·복구·메타데이터는 추가한다. 실제 운영일 수는 달력으로 계산한다.
- FRED 조회료는 $0이지만 지수 공개 게시 허가 비용은 미확인이다. 운영 총액에 $0으로 확정 합산하지 않는다.
- FMP Basic $0/250회·일, Starter $19/월 연 결제 환산(연 $228), 표시·재배포 계약료 미확인. Starter가 필수라는 결론은 아니다.
- Twelve Data 공개 운영 총액은 미확인. 무료 내부 요금제 비용을 공개 운영 비용으로 대입하지 않는다.

## 선택을 끝내기 위해 필요한 확인

1. 제공처/권리자의 문서에서 한국어 X 계정의 일별 종가·계산 등락률 정기 게시와 출처 표기 조건 확인. [S&P 데이터 라이선스](https://www.spglobal.com/spdji/en/about-us/data-index-licensing/)는 미디어 표시 라이선스를 별도로 안내한다.
2. 두 정확한 심볼·가격지수·전 거래일 값·확정 여부를 최소 샘플로 대조.
3. 07:30까지 확보·08:00 게시에 맞는 도착 시각을 여러 거래일 관찰. 지연·휴장·수정치를 함께 시험.
4. 별도 허가가 필요하면 사용자가 원할 때 문의할 수 있도록 용도·글 수·정기성·계정·보관 범위를 정리. 이번에는 문의하지 않았다.

발표에서는 “FRED의 정확한 두 계열은 확인했지만 무료 조회와 공개 게시 권한은 다르고, 현재 갱신 표시도 아침 목표를 충족한다고 확인되지 않았다”를 설명할 수 있다. 지수나 예산·발행 시각을 바꾸는 결정은 자동으로 하지 않는다.

## 후속 조사: 샘플·권한·현재 구성 적합성

추가 확인일은 2026-10-22 KST다. 다음 결과는 공개 페이지와 공식 데모의 실제 열람 결과이며 인증된 운영 API 시험은 아니다.

### 공개 자료 검증 결과

[SP500](https://fred.stlouisfed.org/series/SP500)·[NASDAQ100](https://fred.stlouisfed.org/series/NASDAQ100)를 다시 열어 같은 10월 21일 거래일과 위 갱신 표시를 확인했다. 페이지에서 10월 20일·21일 값의 날짜·숫자·동일 계열 여부를 확인하고 PowerShell Decimal로 등락률 계산을 실행했다. 결과는 SP500 +0.58%, NASDAQ100 +1.13%였다. **웹페이지 자료에 대한 산술 확인**이며 FRED API JSON 응답이나 최초 수록 시각의 검증 결과는 아니다. 결과를 현재 투자 정보로 게시하지 않았다.

FRED 공식 CSV 내보내기 주소(`graph/graph.csv`, 두 series ID와 시작·종료일 사용)는 웹 도구가 접근 불가를 반환해 CSV 확보·파싱 검증을 완료하지 못했다. 접근 제어 우회나 대체 비공식 다운로드는 하지 않았다. 따라서 “키 없는 CSV 연동 성공”으로 발표하지 않는다.

### FRED 라이선스에서 더 확인된 제약

[SP500 주석](https://fred.stlouisfed.org/series/SP500)의 짧은 핵심 문구는 “prior written permission”이다. [FRED 약관](https://fred.stlouisfed.org/legal/)의 Data/Third-party·API 부분은 일반적인 FRED 사용 허가가 민간 시리즈 소유자의 조건을 덮어쓰지 않는다고 설명한다. 같은 문서의 Prohibitions (p)와 API Restrictions (l)에는 저장·캐시·아카이브·DB 편입 제한도 있다. 다운로드 기능이 있다는 사실을 무기한 운영 DB 보관 허가로 해석하면 안 된다.

| 작업 | 공개 근거 판정 | 필요한 확인 |
| --- | --- | --- |
| 개인 연구에서 계열 열람·형태 검토 | 무료 열람·개인 사용 안내 확인 | 운영 서비스와 구분 |
| 종가·계산 등락률의 정기 X 게시 | 제3자 시리즈 권리 및 사전 허가 조건 적용 | S&P·Nasdaq 및 FRED 적용 조건 확인 |
| 지수 원자료의 외부 AI 전달 | 이 두 계열에 대한 별도 허용 확인 안 됨 | 제공자 처리·제3자 접근 범위 서면 확인 또는 코드로만 계산 |
| 원자료·근거·게시문의 DB/백업 보관 | 저장 제한 문구와 현재 보관 요구가 충돌 가능 | 허용 기록 범위·기간·종료 후 처리 확인 |

이는 정책 원문에 따른 채택 보류 판단이다. 개별 수치에 대한 법률상의 권리 성립 여부를 확정하는 법률 의견은 아니다. 비상업 계정·출처 표기·등락률 계산만으로 약관 문제가 해결된다고 가정하지 않는다.

### 추가 후보: Alpha Vantage

[공식 문서](https://www.alphavantage.co/documentation/)에서 `INDEX_DATA`, `symbol=SPX/NDX`, `interval=daily`로 두 정확한 지수 일별 OHLC를 제공하는 Premium 기능을 확인했다. 문서의 SPX·NDX 주간 [SPX 데모](https://www.alphavantage.co/query?function=INDEX_DATA&symbol=SPX&interval=weekly&apikey=demo)·[NDX 데모](https://www.alphavantage.co/query?function=INDEX_DATA&symbol=NDX&interval=weekly&apikey=demo)를 실제 열었으나 두 응답 모두 `Information` 필드의 키 발급 안내만 반환했다. 성공 데이터나 일별 샘플로 기록하지 않는다.

[약관 §2](https://www.alphavantage.co/terms_of_service/)는 기본 허가를 개인·비상업 사용으로 두고 그 밖의 사용에 서면 합의를 요구하며, 사적·개인적 분석을 넘어서는 경우도 상업 사용 정의에 포함한다. [Premium](https://www.alphavantage.co/premium/)은 지수 데이터의 별도 entitlement 절차를 안내한다. 실제 금액·공개 표시 권한·아침 도착은 미확인이다. 무료 대체 경로로 채택하지 않는다.

### 후속 판정과 준비 항목

- **확인 완료:** 정확한 두 FRED 계열, 웹페이지의 거래일·숫자 형식, 전일 대비 산술, 현재 표시된 갱신 시각, 제3자 권리와 보관 제한 문구.
- **미확인:** 운영 API 응답, 07:30 최초 수록 보장, 실제 허가·라이선스 총액, 보존 가능한 원자료/파생 기록의 범위.
- **필요한 준비:** 제공처 허가 자료 또는 요청별로 용도를 명시한 서면 답변, 사용자가 준비한 적법한 키, 최소 두 지수·연속 거래일 샘플과 휴장/수정 사례. 요청서에는 정기 X 게시·최대 글 수·한국어·출처·등락률 계산·AI 전달 여부·30일 근거 및 게시 이력 보존을 각각 명시한다. 문의·가입은 실행하지 않았다.
- **현재 약 2.1만 원 로컬 비용 구성에 대한 결론:** 조회료 $0만 반영하면 계산상 여유가 생기지만 필수 공개 권한이 없으므로 실제 운영 적합 판정은 계속 보류한다. 별도 허가 비용을 0원으로 숨기지 않는다.
