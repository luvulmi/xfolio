# T07 무료 실조회와 본인 Telegram 진단 집계

- 관측:2026-11-05 09:22:59~09:23:19, Asia/Seoul
- [집계](실조회_집계.json) · [수행 결과와 한계](../../../../logs/2026-11-05_아침_뉴스레터_통합_인수.md)

`scripts/experiments/newsletter_integration_probe.py`의 명시적 실행으로 KIS3종목·Finnhub/BLS/BEA/Board 수집·본인private Telegram 시험 메시지1회를 확인했다. 저장 서비스는 격리된 일회용PostgreSQL schema에 연결하고 종료 후 제거했다. 최초 다른role 구성의 진단은 외부 호출 전에 실패했으며 이 집계는 수정한 별도시험DB의 성공 실행이다.

Telegram 전송은 가격/뉴스가 없는 T07 시험 표시 통신확인1회다. API의 성공 응답을 뜻하며 사람이 읽음·실제 아침 뉴스레터 정시수신을 뜻하지 않는다. 기사 선정은 정상0건이고 유료 AI 호출0회다. 실제07:50/08:00 관측·Google/AWS 운영 인수를 대신하지 않는다.

키·chat ID·DB자격·원문·기사제목/주소·가격 수치 없이 상태/건수/시각과Telegram message ID만 보존했다. `.cache` 실행 원본의 안전 집계 사본이며 운영입력 fixture로 재사용하지 않는다.
