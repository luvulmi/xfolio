# Python 애플리케이션

2026-11-05 기능별 패키지 구조다. 루트에는 `cli.py`, `__main__.py`, `__init__.py`만 두며 실행 명령은 기존 `uv run xfolio ...`를 유지한다. 파일이 있다는 사실과 실제 운영 인수는 구분한다. [전체 구조](../../docs/프로젝트_구조.md) · [테스트](../../tests/README.md)

| 패키지 | 책임·주요 파일 |
| --- | --- |
| `domestic/` | 국내 ETF. `kis.py` 시세·토큰, `calendar.py` 거래일, `catalogue.py` 마스터/검색, `models.py` 계약, `store.py` 저장, `cli.py` 조회 |
| `news/` | `collection.py` 현재4출처 수집·중복/중요도/요약 연결, `importance.py` 중요도, `collection_store.py` 기발송·90일 저장, `cli.py` 진단. `contracts.py`·`input.py`·`evaluation.py`·`selection.py`는 공통 근거/입력과 기존 검토 계약 |
| `news/providers/` | `finnhub.py` 일반 뉴스, `official.py` BLS/BEA/Board 자체 발표, `bls.py` CPI 파서. `exa.py`·`bls_input.py`는 이전 공통 입력 어댑터 |
| `ai/` | `generation.py` OpenAI 어댑터/토큰 상한, `workflow.py` 단가·예산 예약·생성 결과 계약, `validation.py` 기존 사실/문형·길이 검사 |
| `newsletter/` | `edition.py` 가격+뉴스 아침 편성·발송 직전 검사, `store.py` 불변 편성/90일, `settings.py` 공용 알림 설정/revision/감사, `cli.py`·`demo.py` 무통신 편성 시험 |
| `jobs/` | `collection.py`07:50 설정/종목 고정·실수집·준비 claim, `worker.py` 예약/단계 실행, `outbox.py` 원자 점유·재시작/중복·429/불명, `telegram.py` 분할/송신 |
| `api/` | FastAPI·Google 세션/CSRF·관리자 종목/설정·비용/신선도·뉴스레터/발송 이력. 기존 X 검토 API도 보존 |
| `db/` | SQLAlchemy schema. 실제 DB 변경 이력은 [migrations](../../migrations/README.md) |
| `legacy/` | 기존 미국 ETF/지수(`etf.py`, `market.py`, `models.py`), X AM/PM 편성, 합성 분석/미리보기, SQLite/PostgreSQL 미리보기 저장·Streamlit/클라우드 시험 자산 |

기본 연결은 `domestic`·`news` → `newsletter` → `jobs`이며 `api`는 저장된 결과와 설정을 조회·수정한다. `db`는 저장 schema, `ai`는 생성·예산 계약이다. 일반 뉴스의 제목·링크와 공식 발표의 근거 요약을 구분한다. [중요도 단일 기준](../../docs/뉴스_중요도_기준.md)

`news/collector.py`·`models.py`·`queries.py`·`store.py`는 이전 Marketaux 수집/메타데이터·근거 저장을 보존한다. 현재 운영 후보는 `news/collection.py`에서 확인한다. 기존 CLI와 API 경로는 유지하며 Python 내부 import는 새 패키지를 사용한다. 예: `xfolio.news_importance` → `xfolio.news.importance`, `xfolio.newsletter_store` → `xfolio.newsletter.store`.

실제 로컬은 HTTPS8443/API18443/DB55439다. 준비/송신의 기본 모드는 모의이며 live는 명시적 서버 설정·본인 수신자·유효 단가/예산이 필요하다. 실제 유료1건 진단·11/6 예약 준비와 정시 수신·AWS 운영 인수는 [수행 기록](../../tasks/logs/2026-11-05_뉴스_중요도와_로컬_실행.md)에서 구분한다.
