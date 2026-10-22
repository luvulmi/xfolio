# 작업 문서

진행 중인 작업은 주제별 파일에 기록합니다. 작업하면서 결정한 요구사항과 설계 내용은 `docs/`에 정리합니다.

| 작업 | 문서 |
| --- | --- |
| 시장 데이터 수집 | [market_data_collection.md](market_data_collection.md) |
| 뉴스 수집 | [news_collection.md](news_collection.md) |
| X 게시 흐름 | [publishing_workflow.md](publishing_workflow.md) |
| 3주차 기술·비용 조사 | [week3_research_plan.md](week3_research_plan.md) |

3주차 항목별 조사 결과와 기술 구성·비용 결론은 [조사 문서 목록](../docs/research/week3/README.md)에 정리합니다.

조사 후 사용자가 선택한 실행·저장·발행량과 비용 기준은 [초기 비용 절감 구성](../docs/minimum_cost_configuration.md)입니다.

2026-10-23 지수 수집 수단을 [yfinance](../docs/research/week3/yfinance_index_collection.md)로 확정했습니다. [지수 수집·게시 모드](../docs/market_search_and_publishing_modes.md)에 따라 종가 조회·등락률 계산과 개발·테스트 승인 → 안정화 후 자동 게시를 구현합니다. 설치·실제 연동은 아직 수행하지 않았습니다.

날짜별 진행 내용은 [progress/](progress/README.md)에 `YYYY-MM-DD.md` 형식으로 기록합니다. GitHub Issues로 업무 목록을 관리하게 되면 이곳에 같은 목록을 중복해서 작성하지 않습니다.

브레인스토밍 기록은 [brain_storm/](brain_storm/README.md)에 세션별로 남깁니다.

현재 프로젝트의 개발 범위는 [미국 시장 브리핑 세션](brain_storm/session_2026-10-15_market_briefing_redesign.md)의 Q36에서 확정했습니다.

3주차 사전 조사 전의 상세 기획 점검은 [상세 기획 세션](brain_storm/session_2026-10-21_pre_research_planning.md)에 기록합니다. Q14까지 개별 결정 후 사용자의 일괄 정의 요청에 따라 [세부 운영 추천안](../docs/market_briefing_operating_plan.md)을 작성했습니다. 확정 정책과 새 추천값·조사 의존 항목을 구분합니다.

XFolio 시장 브리핑 AI 에이전트의 확정 범위·미결정 사항과 이전 ETF 설계 이력은 [market_briefing_agent_design.md](../docs/market_briefing_agent_design.md)에 정리합니다.

설계 참고 사례와 확인 범위는 [similar_service_research.md](../docs/research/similar_service_research.md)에 정리합니다.

TIGER·KODEX ETF의 장중·일별 시세 조회 기능과 X 공개 게시 조건 조사는 [etf_market_data_research.md](../docs/research/etf_market_data_research.md)에 정리합니다.

미국 두 지수 마감 브리핑의 무료 제공처와 공개 게시 조건 조사는 [us_index_data_research.md](../docs/research/us_index_data_research.md)에 정리합니다.

## 진행 기록

- [1주차 발표 메모](progress/2026-10-11.md)
- [2주차 요구사항 발표 메모 (10/18)](progress/2026-10-18.md)
- [2주차 발표 대본 (10/18)](progress/scripts/2026-10-18.md)
- [3주차 발표 초안 (10/21)](progress/2026-10-21.md)
