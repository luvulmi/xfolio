# 데이터베이스 변경 이력

Alembic으로 PostgreSQL 운영 schema의 변경 순서를 관리한다.

| 위치 | 역할 |
| --- | --- |
| `env.py` | 명시적 migration 연결 설정과 SQLAlchemy metadata 연결 |
| `versions/0001_operational_schema.py` | 초기 운영 schema migration |
| [schema.py](../src/xfolio/db/schema.py) | 애플리케이션의 현재 테이블 정의 |

실제 실행 절차는 [루트 README](../README.md)를 따른다. `XFOLIO_MIGRATION_DATABASE_URL` 또는 명시적 연결을 사용하며 `.env`와 기존 미리보기 DB 설정을 자동으로 읽지 않는다. migration 파일이 있다는 사실이 특정 DB에 적용되었다는 뜻은 아니다.

새 schema 변경은 `versions/`에 추가하고 관련 API·DB 시험을 함께 검증한다. 기존 적용 이력을 파일 이동이나 번호 재정렬로 바꾸지 않는다.

[검증 안내](../tests/README.md) · [문서 목록](../docs/README.md)
