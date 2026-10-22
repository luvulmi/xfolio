# R6. 저장소·관리자 사이트 조사

- 확인일: 2026-10-22, Asia/Seoul
- 범위: 공식 문서 조사와 임시 DB 기능 실험. 서비스 생성·로그인 연동·실제 앱 DB 성능·운영 DB 복원 시험은 수행하지 않았다.
- 기준: [3주차 조사계획](../../../tasks/week3_research_plan.md), [운영 추천안](../../market_briefing_operating_plan.md)
- 관련: [예약 실행·배포](scheduling_deployment.md)

## 조사 결론

후속 결정: 사용자가 [초기 비용 절감 구성](../../minimum_cost_configuration.md)을 선택해 SQLite·Streamlit을 기존 Windows PC에 함께 두기로 정했다. 아래 Linux VM·관리형 DB 비교는 조사 이력이다.

후속 조사 기준의 첫 버전은 **현재 Windows PC에 SQLite와 로컬 Streamlit, 작업 스케줄러를 함께 두는 구성**이다. 유료 VM 없이 동일 호스트의 공통 기록을 사용한다. 앞선 Linux VM 비교는 향후 상시 운영 대안으로 남긴다. 운영자 1명과 작은 발행량에서는 별도 DB 서버와 네트워크 연결을 줄일 수 있다. Python 3.12의 `sqlite3`로 시작하고 DB 접근 코드를 한 곳에 모은다. 이는 조사에 따른 추천이며 구현 완료가 아니다.

사이트와 작업을 서로 다른 호스팅에 배치한다면 SQLite 파일 공유 대신 Supabase PostgreSQL 같은 원격 DB를 사용한다. 무료 DB는 가능하지만 휴면·백업·연결 설정을 추가로 관리해야 한다. [Python sqlite3 문서](https://docs.python.org/3.12/library/sqlite3.html), [SQLite 적합한 용도](https://www.sqlite.org/whentouse.html)

## 후보 비교

| 후보 | 지원·공통 기록 접근 | 비용·제약 | 구현·운영 판단 |
| --- | --- | --- | --- |
| SQLite + 같은 서버의 Streamlit·작업 | 프로세스들이 같은 로컬 DB를 사용. 트랜잭션과 고유 제약으로 승인·한도·발행 상태 보호 | 별도 DB 서비스 구독 없이 서버 디스크 사용. 서버와 백업 비용 별도. 한 번에 쓰기 작업 1개 | 우선 추천. 짧은 쓰기 트랜잭션과 단일 게시 작업으로 작은 동시성을 관리 |
| Supabase Free PostgreSQL + 별도 사이트·작업 | 네트워크 DB로 여러 실행 환경의 기록 통합 | $0/월, DB 500MB·egress 5GB·파일 1GB. 저활동 약 7일이면 pause 가능. 자체 백업 필요 | 분리 배포 대안. 무료가 항상 켜짐이나 자동 복원을 보장하지 않음 |
| Supabase Pro PostgreSQL | 관리 DB와 자동 일일 백업 | $25/월 시작, 첫 프로젝트 포함·백업 7일. 추가 자원/프로젝트 과금 별도 | 월 3만 원 전체 예산에서 우선 제외. 지수·뉴스·AI·X 비용까지 고려하면 부담 |

SQLite의 동시 쓰기와 로컬 사용 조건은 [적합한 용도](https://www.sqlite.org/whentouse.html)와 [WAL 문서](https://www.sqlite.org/wal.html), Supabase 금액·포함량은 [공식 가격](https://supabase.com/pricing), pause는 [Project Pausing](https://supabase.com/docs/guides/platform/free-project-pausing), 백업은 [Database Backups](https://supabase.com/docs/guides/platform/backups)를 확인했다. 무료 DB의 500MB와 파일 저장 1GB는 서로 다른 항목이다.

## 추천 데이터 흐름

```text
수집·AI 작업 → 공통 DB의 근거·후보 버전·검증 결과
                         ↓
                  Streamlit 운영자 검토
                         ↓
               승인 버전·일일 한도 예약 저장
                         ↓
              게시 작업이 승인 상태를 다시 확인
                         ↓
                 X 결과·게시물 ID 기록
```

화면은 이미 있는 Streamlit을 사용한다. 후보 문안·출처·시각·검증·승인/보류·게시 결과·마지막 실행·비용을 보여 주고, 승인 상태만 DB에 기록한다. 화면 버튼에서 외부 게시를 직접 실행하지 않는 설계다. DB 제품이 정확성을 자동 보장하지는 않으므로 아래 항목을 애플리케이션에서 구현해야 한다.

- 기사·사건·근거 버전, 초안 버전, 승인자·승인 시각, 발행 건·글 순서·X ID, 실행·비용 기록을 분리한다.
- 고정 후보 버전을 조건으로 승인하고, 같은 발행 키의 중복 생성을 DB 고유 제약으로 막는다.
- 승인 예약·한도 검사·게시 작업 점유는 짧은 트랜잭션으로 처리한다. 외부 API 응답을 기다리는 동안 DB 쓰기 잠금을 유지하지 않는다.
- 전송 전 상태와 응답 후 ID를 각각 기록한다. 중간 종료는 성공 불명으로 보존하고 재전송하지 않는다. DB 트랜잭션과 X 전송을 하나의 원자적 작업으로 만들 수 있다고 보지 않는다.

## SQLite 운용 조건

Streamlit과 작업은 같은 서버의 지속 디스크에 접근한다. GitHub Actions가 파일을 내려받아 수정한 뒤 다시 업로드하는 방식, 네트워크 공유 폴더에 WAL DB를 놓는 방식은 채택하지 않는다. WAL은 같은 호스트의 프로세스 사용이 전제다. [SQLite WAL](https://www.sqlite.org/wal.html)

단일 게시 작업을 기본으로 하고, 쓰기 경합 시 제한된 대기·재시도 및 실패 기록을 둔다. DB 연결을 화면 사용자 사이에서 무분별하게 공유하지 않는다. 서버가 늘어나거나 동시 쓰기가 커지면 PostgreSQL로 이전하는 것이 다음 선택이다. 현재 규모에 충분하다는 성능 측정은 아직 없다.

백업은 실행 중인 `.db` 파일만 단순 복사하지 않고 Python `Connection.backup()` 또는 SQLite Online Backup API로 일관된 사본을 만든다. 일일 백업을 서버 밖에도 보관하고, 빈 DB에 실제 복원해 승인·발행 키·게시물 ID를 확인한다. 서버 스냅샷은 보조 수단이며 애플리케이션의 백업·복원 시험을 대신하지 않는다. [Python backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup), [SQLite Online Backup](https://www.sqlite.org/backup.html)

Supabase Free를 택하면 CLI `db dump` 등의 자체 외부 백업을 예약해야 한다. Supabase DB 백업에는 Storage API로 넣은 실제 파일이 포함되지 않으므로 근거 파일을 별도 저장할 경우 별도로 보존한다. [Supabase 백업](https://supabase.com/docs/guides/platform/backups)

## 관리자 로그인

Streamlit은 OIDC 로그인용 `st.login()`, 사용자 정보 `st.user`, 로그아웃 `st.logout()`을 제공한다. Google Identity 등 제공처의 앱 등록·redirect URI·client ID·secret·cookie secret 설정이 필요하다. **로그인 성공과 운영자 권한은 구별**하며 서버에서 허용된 계정의 issuer·subject를 확인한 뒤 근거 조회와 상태 변경을 허용한다. 사이트 로그인으로 X API 권한이 생기는 것은 아니다. [Streamlit 인증](https://docs.streamlit.io/develop/concepts/connections/authentication)

이 문서의 쿠키 만료 기본값은 30일이며 제공처 토큰 만료와 직접 연결되지 않는다. 필요 시 토큰의 만료를 별도로 확인해야 한다. 승인 요청마다 로그인·허용 계정·후보 버전을 재검사하고, 인증 비밀은 저장소 밖에 둔다. OIDC 제공처 계정·요금·등록 가능성은 실제 연동 전에 확인한다. [Streamlit 인증](https://docs.streamlit.io/develop/concepts/connections/authentication)

Streamlit Community Cloud는 12시간 방문이 없는 앱을 휴면 처리한다. 따라서 무료 사이트를 곧바로 상시 작업 서버로 사용하지 않는다. 별도 외부 DB와 스케줄러를 연결하는 경우 관리 화면 용도로는 검토할 수 있지만, 재시작 후 로컬 파일 보존을 운영 DB의 계약으로 삼지 않는다. [Community Cloud 관리](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)

## 비용 입력과 남은 확인

- SQLite 자체 DB 구독액은 $0 추가, VM·백업 비용은 [R7](scheduling_deployment.md)에서 합산한다. 호스팅 비용을 다시 DB 항목에 중복 더하지 않는다.
- Supabase Free는 현재 포함량 안에서 $0이지만 백업 저장·작업 호스팅·OIDC 제공처 비용까지 $0으로 확인한 것은 아니다.
- Supabase Pro는 기본 $25부터이며 세금·환율·초과량은 별도다. 전체 월 비용에서 무료안과 유료안을 따로 계산한다.
- 실제 뉴스 저장 가능 조건, 월 레코드 수·근거 크기·DB 증가량, 1GB VM 메모리, 동시 승인/게시 경합, 로그인/로그아웃, 백업 복원은 4주차 최소 연동 시험에서 확인한다.

문서 조사 단계에서 DB·사이트를 새로 생성하거나 키를 확인하지 않았다. 서비스별 보관 가능 용량이 기사 전문 저장 권한을 뜻하지 않는다.

## 후속 확인: 현재 Windows PC와 SQLite 실험

로컬 Streamlit은 `127.0.0.1`에만 바인딩하고 같은 PC의 브라우저로 검토하는 구성을 제안한다. 공용 IP·포트 전달·터널·외부 호스팅은 첫 시험에 필요하지 않다. 이는 다른 기기에서 원격 검토하는 기능을 제공하지 않는 구성이다. 사용자별 데이터 폴더와 DB 파일 권한을 제한하고 Git에 넣지 않는다. 본 실험에서 화면이나 네트워크 서버를 실제 실행하지 않았다.

2026-10-22 기존 `.venv`의 `importlib.util.find_spec` 확인 결과 `streamlit=False`, `authlib=False`였다. `pyproject.toml`에는 `dashboard = ["streamlit"]`만 선언되어 있다. 따라서 선택 의존성 선언을 설치·실행·로그인 완료로 보지 않는다. `st.login`에는 공식 문서상 `Authlib>=1.3.2` 또는 `streamlit[auth]`가 필요하므로 로그인 구현 시 선택 의존성과 lock을 갱신할 작업이 남는다. 이번 조사에서는 의존성을 추가하거나 OIDC 계정을 등록하지 않았다. 로컬 callback 예시는 `http://localhost:8501/oauth2callback`이다. [Streamlit st.login](https://docs.streamlit.io/develop/api-reference/user/st.login)

외부 API 없는 [재현 스크립트](experiments/sqlite_probe.py)를 추가해 임시 DB만 생성·삭제했다. 실행 명령은 저장소 루트 기준 `.\.venv\Scripts\python.exe docs/research/week3/experiments/sqlite_probe.py`다. 처음 샌드박스 임시 경로 권한 때문에 열기에 실패했으며 허용된 권한 재실행에서 아래 결과를 얻었다. `uv run`도 캐시 권한 오류가 있어 실제 실험은 기존 가상환경 실행 파일을 사용했다.

| 항목 | 실제 환경·방법 | 결과 |
| --- | --- | --- |
| 실행 환경 | Windows 11 build 26200, Python 3.12.10, SQLite 3.49.1, WAL | 전체 0.1996초. 처리량 측정값은 아님 |
| 중복 발행 키 | 두 스레드 각각 독립 연결, barrier 이후 같은 PRIMARY KEY INSERT 시도 | 예약 1건 성공, 나머지 1건 `IntegrityError`로 거절 |
| 승인 버전 조건부 갱신 | 현재 v2에 대해 v1 승인, v2 승인, v2 재승인 | 갱신 행 수 각각 0·1·0 |
| 트랜잭션 롤백 | 후보 변경·발행 예약 INSERT 후 의도적 예외 | 후보 v2 유지, 롤백 대상 예약 0건 |
| 백업·복원 | `Connection.backup`으로 사본 생성, 원 DB 수정 뒤 사본에서 새 DB 복원 | 후보 v2·승인 v2·가짜 게시물 ID 보존, `integrity_check=ok` |
| 데이터 처리 | `TemporaryDirectory` 안의 가짜 기사/게시 ID만 사용 | 성공 실행의 임시 디렉토리 정리 완료, 실제 앱 데이터 변경 없음 |

이는 **SQLite 기능의 작은 독립 실험**이다. XFolio 승인·게시 파이프라인은 아직 이 로직을 구현하지 않았다. 두 프로세스 강제 종료·전원 차단·OS 재부팅·X 전송·동시 한도 예약·월 저장량·운영 백업까지 검증한 것은 아니다. 일관된 DB 복원만으로 X에 이미 게시한 결과까지 되돌릴 수 없으므로 복원 뒤 외부 게시 결과 대조가 필요하다. 실행 코드의 Ruff 검사·형식 검사를 통과했다.
