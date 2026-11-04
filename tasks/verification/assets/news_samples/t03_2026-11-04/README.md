# T03 무료 수집·공식 발표 파싱 근거

- 기준: 2026-11-04, Asia/Seoul. 수동 개발 진단이며 제품07:50/08:00 정시 관측과 구분한다.
- [계약/시험](../../../news/뉴스_수집과_요약_통합.md) · [작업 결과/공수](../../../../logs/2026-11-04_뉴스_수집과_요약_통합.md).

| 파일 | 실제 내용 |
| --- | --- |
| [첫 수집](collection_summary.json) | 17:17 KST. Finnhub partial·BLS response_limit·BEA/Board complete. 최초 실패를 보존 |
| [BLS 상한 보완 후 수집](collection_after_bls_limit.json) | 17:19 KST. Finnhub partial·공식3기관 complete·직접 링크3건. GET4+HEAD12=16요청 |
| [공식 파싱 확인서](official_parser_receipt.json) | 실조회한 CPI/GDP/PCE/FOMC 4표본을 재파싱. 확보 파일mtime·발행시각·bytes·해시·사실 수만 기록 |

Finnhub는 원매체 HEAD 예산12회로 경유6건을 제외하고 추가5건은 검증하지 못했다. 부분 수집을complete로 취급하지 않는다. 공식 발표는 모두 해당96h 밖이어서 최신 후보0건이 정상이다. 파싱 확인서는 실제 공식 자료의 사실 추출 근거이며 유료 AI 요약 성공 기록이 아니다.

일반 기사 본문/이미지·공식 원문/발췌·키/토큰은 보존하지 않는다. JSON의 허용 URL/발행·조회시각/해시/집계만 유지한다. 유료AI0·제품DB저장0·Telegram송신0·운영DB적용0이다.
