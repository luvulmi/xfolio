# SEC 기업 공시 발견·한국어 미리보기 시험

- 확인: 2026-10-25, Asia/Seoul
- 범위: NVDA·AAPL·MSFT의 과거 실적 발표 각 1건. **과거 재생·비게시 시험**이며 실시간 수집 성공을 뜻하지 않는다.
- 출력: [OpenAI 사용량·초안·기계 검사 JSON](assets/sec_fact_card_preview_20261025.json)

## 발견 경로와 권리

[SEC Submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)는 CIK별 최신 공시 메타데이터를 인증 없이 JSON으로 제공하고 실시간에 가깝게 갱신한다고 설명한다. 초기 검색은 `8-K`의 `Item 2.02` 실적 발표 후보를 찾고, 해당 filing index의 `EX-99.1` 원문을 확인하는 방식이 적합하다. [SEC FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)는 공개 EDGAR filing content의 접근·재이용을 허용한다. 다만 실제 자동 HTTP 수집은 [declared User-Agent와 초당 10요청 이하 정책](https://www.sec.gov/about/webmaster-frequently-asked-questions)을 지켜야 한다. 이번에는 사용자 연락처를 임의로 만들어 전송하지 않았으며 **Submissions API 3사 자동 폴링은 실행하지 않았다**.

| 회사·CIK | 확인한 공시와 시각 | 원문 근거 |
| --- | --- | --- |
| NVIDIA · `0001045810` | [8-K Item 2.02, 접수 화면에 2026-08-26 16:21:19 표시](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/0001045810-26-000073-index.html), EX-99.1 | [FY2027 Q2 실적](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm): 매출 $96.2B, 전년 동기 대비 106% 증가 |
| Apple · `0000320193` | [8-K Item 2.02, 접수 화면에 2026-07-30 16:30:28 표시](https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/0000320193-26-000018-index.htm), EX-99.1 | [FY2026 Q3 실적](https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/a8-kex991q3202606272026.htm): 매출 $109.4B, 전년 동기 대비 16% 증가 |
| Microsoft · `0000789019` | [8-K Item 2.02, 접수 화면에 2026-07-29 16:04:53 표시](https://www.sec.gov/Archives/edgar/data/789019/000119312526323632/0001193125-26-323632-index.htm), EX-99.1 | [FY2026 Q4 실적](https://www.sec.gov/Archives/edgar/data/789019/000119312526323632/msft-ex99_1.htm): 매출 $90.0B, 전년 동기 대비 18% 증가 |

따라서 이 **세 과거 실적 사건은 SEC 경로에서 3/3 확인**했다. 이는 전 분야 회사 뉴스의 완전 탐색률이나 아침 07:30 이전 도착을 입증하지 않는다. 처음 범위는 실적 공시로 더 좁히고, 다른 사업 변화는 수집 계약·근거·권리를 별도 검증한다. 공시 수신 시각과 회사 발표 시각을 구별하며, 수정 8-K/A·동일 사건 중복은 보류 후 재검토한다.

[NVIDIA는 공식 보도자료 RSS](https://investor.nvidia.com/investor-resources/rss/default.aspx)를 제공한다. [Apple 사이트 약관](https://www.apple.com/legal/internet-services/terms/site.html)은 자동 페이지 수집과 콘텐츠 복제·번역·재게시를 제한하고, [Microsoft 사이트 약관](https://www.microsoft.com/en-us/legal/terms-of-use)은 문서의 재배포·변형을 제한한다. 회사 웹페이지는 사람의 원문 대조 링크로 두고 세 회사 사이트를 일괄 크롤링하는 구현은 하지 않는다. SEC 경로에서도 본문을 X에 복사하지 않고 확인한 사실만 새 한국어 문장으로 요약한다.

## OpenAI 실제 비게시 시험

[실험 스크립트](../../scripts/experiments/sec_fact_card_preview.py)는 위 세 EX-99.1에서 직접 대조한 **주체·분기·매출·전년 동기 증가율의 짧은 사실 카드**만 OpenAI Responses API `gpt-5.4-mini`에 보냈다. `store=False`, 도구 없음, 최대 3회이며 회사 원문 본문·MarketNewsAPI 기사 본문은 전송하지 않았다. 링크는 모델 출력이 아니라 Python이 붙였다. 초안은 `can_publish=false`로 저장했다. [OpenAI 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)과 [모델 단가](https://developers.openai.com/api/docs/models/gpt-5.4-mini)를 사용했다.

| 회사 | 입력/출력 토큰 | 계산 비용 | 필수 사실·새 숫자·한국어·280 가중 길이 |
| --- | ---: | ---: | --- |
| NVIDIA | 240/93 | $0.00059850 | 4/4 통과, 118/280 |
| Apple | 241/92 | $0.00059475 | 4/4 통과, 125/280 |
| Microsoft | 239/91 | $0.00058875 | 4/4 통과, 116/280 |
| **합계** | **720/276** | **$0.00178200 ≈ 3.23원**(계획 환산) | **3/3 비게시 초안** |

예: “Apple은 2026회계연도 3분기에 매출 1,094억 달러를 기록해 전년 동기 대비 16% 증가했다고 발표했다.” 뒤에 SEC 원문 링크를 붙인 형식이다. 이는 **7월 사건의 형식 예시**이며 오늘 게시 후보가 아니다. 기계 검사는 글의 모든 의미 오류를 잡지 못한다. 관리자 육안 대조와 원문 버전 확인을 거쳐야 하고, 실제 X 게시 기능·승인은 아직 없다.

## 판정

발표용 초기 경로는 **BLS CPI + SEC EDGAR의 세 회사 실적 공시**로 바꿀 것을 제안한다. 무료·권리·세 사건의 근거 측면에서 유료 기업 뉴스 피드보다 현재 증거가 좋다. 다만 자동 Submissions 폴링·EX-99.1 파서·도착 지연·8-K/A·승인과 게시 연동은 미완료다. 따라서 이번 작업의 결론은 **근거 경로와 작은 AI 미리보기 검증**이며 운영 자동화 확정이 아니다.
