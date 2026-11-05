# 데이터베이스 변경 이력

Alembic으로 PostgreSQL 운영 schema의 변경 순서를 관리한다.

| 위치 | 역할 |
| --- | --- |
| `env.py` | 명시적 migration 연결 설정과 SQLAlchemy metadata 연결 |
| `versions/0001_operational_schema.py` | 초기 운영 schema migration |
| `schema_0001.py` | 0001 당시 8테이블 DDL 고정 snapshot. 현재 metadata와 분리 |
| `versions/0002_am_four_posts.py` | reserved_count 0~4·post position 1~4 전환 |
| `versions/0003_domestic_market.py` · `schema_0003.py` | 국내 종목·관심목록/버전·휴장일 일일 점유/캐시·수집·원종가90일의 신규7테이블/trigger, 고정 DDL |
| `versions/0004_newsletter_news.py` · `schema_0004.py` | 뉴스 수집/선정 메타데이터·본인 수신자별 전달 결과의 신규3테이블, 최초 저장+90일 만료. 원문/근거 발췌 제외 |
| `versions/0005_morning_newsletter.py` · `schema_0005.py` | morning 편성·준비/부분/실패/휴장 건너뜀·수신자/날짜/슬롯 유일 키·불변 trigger·원본 만료 이내 최대90일 payload. outbox는 별도 |
| `versions/0006_notification_settings.py` · `schema_0006.py` | 공용 알림 설정 singleton·revision·가격 없는365일 설정/관심목록 변경 감사 |
| `versions/0007_telegram_outbox.py` · `schema_0007.py` | mock/live 별도 outbox·조각/시도·원자 점유·가격/뉴스 본문 없는365일 발송 메타데이터 |
| [domestic.py](../src/xfolio/db/domestic.py) | 국내 시장 전용 metadata. legacy8테이블과 분리하며 env.py에서 함께 연결 |
| [schema.py](../src/xfolio/db/schema.py) | 애플리케이션의 현재 테이블 정의 |

실제 실행 절차는 [루트 README](../README.md)를 따른다. `XFOLIO_MIGRATION_DATABASE_URL` 또는 명시적 연결을 사용하며 `.env`와 기존 미리보기 DB 설정을 자동으로 읽지 않는다. migration 파일이 있다는 사실이 특정 DB에 적용되었다는 뜻은 아니다.

새 DB 생성은 연결된 대상에서 `uv run alembic upgrade head`로0001~0007을 순서대로 적용한다. DB/접속 역할은 미리 준비해야 하며 이 명령이 PostgreSQL 서버나 DB 자체를 만들지는 않는다.0006/0007 SQL만 검토할 때는 `uv run alembic upgrade 0005_morning_newsletter:head --sql`을 사용한다. 기존0002의 CHECK 조회 때문에 base→head 전체 오프라인 출력은 지원하지 않는다.

새 schema 변경은 `versions/`에 추가하고 관련 API·DB 시험을 함께 검증한다. 기존 적용 이력을 파일 이동이나 번호 재정렬로 바꾸지 않는다.

0001이 현재 metadata를 참조하던 부분을 당시 DDL snapshot으로 고정했다. 0001의 실제 테이블/인덱스/trigger DDL은 유지하고 0002에서 두 CHECK만 바꾼다. 신규 base→head와 기존 0001→head, downgrade/reupgrade를 일회용 PostgreSQL에서 검증한다. 4번째 위치나 reserved_count=4인 자료가 있으면 0001 downgrade는 실패하며 전체 트랜잭션을 되돌린다. 운영 DB migration은 자동 수행하지 않는다.

[검증 안내](../tests/README.md) · [문서 목록](../docs/README.md)
