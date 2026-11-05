# T04 · 합성 아침 뉴스레터 표본

- 생성: 2026-11-04, Asia/Seoul. `newsletter_demo.demo_inputs` → `build_morning`.
- 모든 가격·기사·GDP 수치는 합성이고 기사 주소는 형식 검사용이다. 외부 API·AI·DB·Telegram 호출0회이며 실제 발송 가능 판정은 항상 false다.

| 표본 | 상태 |
| --- | --- |
| [정상3건](정상_3건.txt) | ready, 가격3·일반2+공식1 |
| [정상0건](정상_0건.txt) | ready, 적격 뉴스 없음 |
| [부분 실패](부분_실패.txt) | partial, 가격1종목 누락·BLS 수집 실패 |
| [전체 실패](전체_실패.txt) | failed, 사용 자료 없음·발송 보류 |
| [휴장 건너뜀](휴장_건너뜀.txt) | skipped,12/25 한국 휴장 평일·발송 없음 |

[상태 집계](상태_집계.json) · [검사 계약](../../../integration/아침_뉴스레터_편성과_발송_검사.md)
