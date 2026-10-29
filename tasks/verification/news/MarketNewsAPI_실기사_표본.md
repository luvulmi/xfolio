# MarketNewsAPI 실기사 표본과 채택 판정

- 시험 시각: 2026-10-25 01:55 KST(응답 기준 2026-10-24 16:55 UTC)
- 범위: Free 계정의 인증 API, NVDA·AAPL·MSFT, `press_release`·`news` 각 첫 페이지 3건. 추가로 공식 실적 발표 3건을 날짜·문구로 대조했다.
- 원자료: [본문·키를 제외한 응답 메타데이터](../assets/news_samples/marketnewsapi_sample_20261025.json). 공개 게시·유료 가입·OpenAI 전송은 하지 않았다.

## 첫 페이지에서 실제 확인한 것

6개 질의가 모두 HTTP 200으로 반환됐다. 18행, 고유 ID 17개이며 6개 모두 다음 커서가 있어 **전체 수집이나 포괄적 품질 평가가 아니다**. Free 응답은 15분 지연을 표시했다. 조회 당시 `/v1/usage`는 `23/100 requests_today`, 잔여 77을 반환했다. 보도자료 9건과 일반 기사 9건의 발행 시각은 모두 있었지만 `ingested_at`은 18건 모두 없었다. 일반 기사 9건 중 8건의 `summary`가 비었고 9건 모두 `body`가 존재했다. 이는 [기사 객체 문서](https://marketnewsapi.com/docs/article-object)의 일반 기사 본문 설명과 다르므로, 필드가 실제로 반환된다는 사실을 **재이용 허가**로 해석하지 않는다.

상위 보도자료에는 NVIDIA 제품을 판매하는 업체, Webull의 옵션 거래, Microsoft 협력업체의 수상처럼 **관찰 기업의 실적·전망 발표가 아닌 동시 태그**가 섞였다. AAPL 질의에는 식품명인 “Apple”이 걸린 기사도 있었다. 일반 기사 상위에는 주가 전망·의견 기사가 다수였다. 제목·티커만으로 게시 후보를 확정할 수 없고, 원문에서 당사자·사건 시점·수치·조건을 다시 확인해야 한다. 일부 협력 소식은 의미 있는 후보일 수 있으므로 18건 모두를 무가치하다고 판정하지 않는다.

## 알려진 공식 발표와 대조

| 공식 1차 자료 | 제한 API 조회 결과 | 해석 |
| --- | --- | --- |
| [NVIDIA FY2027 Q2, 2026-08-26](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027) | NVDA 보도자료·날짜 창·발표 문구 질의에서 제목 일치 1건 | 이 사례는 발견했다. API 기사와 공식 원문의 일치·도착 시각은 별도 검증 대상 |
| [Apple FY2026 Q3, 2026-07-30](https://www.apple.com/newsroom/2026/07/apple-reports-third-quarter-results/) | AAPL 문구 질의 0건, 발표 날짜의 보도자료·일반 기사 각 0건 | 이 조회에서는 발견하지 못했다 |
| [Microsoft FY2026 Q4, 2026-07-29](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast) | MSFT 문구 질의 0건, 발표 날짜의 보도자료·일반 기사 각 0건 | 이 조회에서는 발견하지 못했다 |

제한된 날짜·필터 시험의 **3건 중 1건 발견**이라는 뜻이다. 2건의 미발견을 서비스 전체의 누락률로 일반화하지 않는다. 다만 이 세 기업의 실적 발표를 놓치지 않는 **단독 기업 피드**라는 용도에는 아직 합격 근거가 없다.

## 이용 조건과 결론

[Free·Pro 가격](https://marketnewsapi.com/pricing)은 일 100요청·15분 지연 / Pro 월 $15이다. [Coverage](https://marketnewsapi.com/coverage)는 미국 상장사·ETF 중심이라 거시 발표를 대체하지 않는다. [AUP](https://marketnewsapi.com/legal/acceptable-use)는 유료 플랜의 단일 기사 자체 요약 예시와 출처·링크 표시를 설명하지만, 일반 매체 전문을 그대로 표시하는 용도는 제한한다. [AI 정책](https://marketnewsapi.com/legal/ai)은 제공 요약의 오류 가능성을 경고한다. 한국어 X 자동 게시, OpenAI API 입력, 근거 보관 기간의 구체적 허용 범위는 운영 전 확인이 필요하다.

**판정:** 초기 3개 기업의 확정 발표를 놓치지 않는 용도로 MarketNewsAPI Pro 가입을 보류한다. 첫 단계의 회사 사건 근거는 각 기업의 **공식 IR·뉴스룸**에서 확인하는 좁은 범위를 제안하고, MarketNewsAPI Free는 선택적 발견·개발 비교에만 둔다. 공식 웹 접근 성공은 자동 수집·재게시 권리나 어댑터 구현 완료가 아니다. IR별 발견 방법·시간 필드·수정 감지·이용 조건을 검증한 뒤 기업 자동 게시 여부를 결정한다.
