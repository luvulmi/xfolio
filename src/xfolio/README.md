# Python 애플리케이션

기능별 모듈의 역할을 정리한 현재 코드 안내다. 모듈이 존재한다는 사실과 실제 외부 연동·운영 완료를 구분한다. 전체 기준은 [프로젝트 안내](../../README.md)와 [문서 목록](../../docs/README.md)을 따른다.

| 경계 | 현재 파일 | 역할 |
| --- | --- | --- |
| 실행 진입 | `cli.py`, `__main__.py` | CLI 상태·조회·미리보기·시험 명령 |
| 시장 수집 | `market.py`, `models.py` | 두 지수 종가·완료 거래일·수집 모델 |
| 뉴스 수집 | `news.py`, `news_models.py`, `news_queries.py`, `bls.py` | 기존 Marketaux 수집 실험과 BLS CPI 근거 파서 |
| 뉴스 처리 | `news_contracts.py`, `news_selection.py`, `news_generation.py`, `news_validation.py`, `news_workflow.py`, `news_edition.py` | 근거 계약·선정·AI 생성·검증·편성. 범용 기사 자동 추출 완료를 뜻하지 않음 |
| 저장 | `storage.py`, `postgres.py`, `news_store.py`, `db/` | 기존 미리보기/근거 저장과 운영 schema |
| 관리자 API | `api/` | FastAPI·Google 인증·검토/승인·운영 조회 |
| 가상 시험 | `demo.py`, `compose.py`, `analysis.py`, `cloud.py`, `dashboard_ui.py` | 가상 입력·미리보기·기존 Streamlit/클라우드 시험 지원 |
| 게시 | `publish.py` | 설명만 있는 미구현 진입점 |

별도 `jobs/` worker와 실제 X 게시 연결은 목표 경계이며 이 안내 작성 시 구현 완료가 아니다. 뉴스 공급자 선택은 재검토 중이므로 기존 Marketaux 코드를 공개 운영 허가의 근거로 보지 않는다.

코드 파일은 import와 CLI 호환성을 위해 현재 위치를 유지한다. 검증 방법은 [테스트 안내](../../tests/README.md), 프론트는 [관리자 앱](../../frontend/README.md), DB 변경은 [migration 안내](../../migrations/README.md)를 참고한다.
