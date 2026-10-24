# 가상 자료 클라우드 시험 배포

이 절차는 Neon의 가상 초안 저장, Google 로그인으로 보호한 Streamlit 미리보기, Cloud Run 단발성 시험 실행을 위한 것이다. 실제 뉴스 수집·AI·승인·X 게시·예약 백업을 배포한 절차가 아니다. 진행·결과는 [전환 계획](../../tasks/plans/클라우드_전환.md)과 [수행 기록](../../tasks/logs/2026-10-25_클라우드_전환_준비.md)을 따른다.

10/25 실제 관리자: [xfolio-yuring.streamlit.app](https://xfolio-yuring.streamlit.app/), 비공개·Python3.12·본인 Google 계정만 허용. 관리자 화면의 가상 저장·조회·중복 방지를 검증했다. Cloud Run은 결제 계정 미연결로 사용자 요청에 따라 보류했다. 아래 GCP 명령은 실행 완료 기록이 아닌 후속 템플릿이다.

## 1. Neon 준비·DB 시험

Free 프로젝트의 PostgreSQL 접속 URL을 `.env`의 `XFOLIO_DATABASE_URL`에 넣는다. 실제 값은 Git·문서·채팅에 남기지 않는다. 드라이버가 CA 검증과 `verify-full`을 강제하므로 URL의 단순 `require` 옵션만으로 TLS 검증을 대체하지 않는다.

```powershell
uv sync --extra cloud --extra dashboard
uv run --extra cloud python -m xfolio.cloud
uv run --env-file .env --extra cloud python -m xfolio.cloud --run --initialize
uv run --env-file .env --extra cloud python -m xfolio.cloud --run
```

첫 명령은 의존성 설치, 두 번째는 무통신 계획이다. `--run`부터 DB를 사용한다. 초기화는 가상 표 하나만 만들고 기존 데이터를 삭제하지 않는다. 성공 결과에는 UTC 관측 시각·왕복·중복 방지 판정을 출력하고 접속 URL·비밀번호·자료 payload는 출력하지 않는다.

기존 **가상 미리보기 표만** 이전하려면 원본이 있는지 확인하고 다음을 실행한다. 실뉴스·수집 커서 등 다른 표의 이전은 후속 작업이다.

```powershell
uv run --env-file .env --extra cloud python -m xfolio.cloud --run --migrate-sqlite data/xfolio.sqlite3
```

SQLite 원본은 read-only로 열고 복사 실패 시 대상 삽입은 트랜잭션으로 롤백한다. 원본을 삭제하거나 운영 전환을 자동 확정하지 않는다. 앱 접속 역할에는 초기화 후 해당 표의 필요한 SELECT·INSERT만 부여하는 것을 권장한다. 운영 DB 역할·권한은 실제 배포 전에 확인한다.

## 2. 비공개 Streamlit 관리자

Community Cloud에서 다음 설정으로 배포한다.

- GitHub 저장소와 배포할 branch: 사용자 저장소의 검토된 커밋을 선택한다. 미커밋 변경은 Cloud에 반영되지 않는다.
- Main file path: **`dashboard/cloud_app.py`**. 로컬용 `dashboard/app.py`를 클라우드 관리자 진입점으로 사용하지 않는다.
- Python: **3.12**. 진입점 옆 `dashboard/requirements.txt`가 루트의 `[dashboard,cloud]` extra를 설치한다.
- Sharing: **Only specific people can view this app**. 허용 운영자만 viewer로 둔다.
- Secrets: [예제](secrets.example.toml)의 항목을 실제 앱 설정에 입력한다. 비밀 파일을 Git에 추가하지 않는다.

Google OAuth 웹 클라이언트를 준비하고 실제 `https://APP.streamlit.app/oauth2callback`을 redirect URI로 등록한다. 동의 화면·테스트 사용자와 허용 운영자 이메일을 확인한다. `cookie_secret`은 충분히 긴 임의 값으로 직접 설정한다. 새 OAuth 클라이언트·비밀·권한과 서비스 약관 동의는 계정 소유자가 확인한다.

설정 누락·미로그인·다른 issuer·미검증 이메일·목록 밖 계정·만료 토큰은 DB를 열기 전에 차단한다. Community Cloud의 비공개 viewer 로그인과 앱의 운영자 OIDC는 별도 확인이다. 공개 링크만으로 운영자로 취급하지 않는다. 실제 비공개·로그인·만료·허용/비허용 계정은 배포 후 시험한다.

실제 접속에서는 Community Cloud의 워크스페이스/허용 viewer 접근을 거친 뒤 앱의 Google 로그인을 진행한다. 로그인 화면이 나타나지 않으면 [워크스페이스](https://share.streamlit.io/)에서 앱 링크를 새로 연다. Google 로그인 완료 후 기본 주소가 로딩 화면에 머무는 현상이 남아 있다. 이때 동일 앱의 [직접 화면](https://xfolio-yuring.streamlit.app/~/+/)으로 이동해 인증된 미리보기·DB 조회가 정상임을 확인했다. Google 로그인 시작은 기본 주소에서 진행한다. 원인과 일반 주소 접속 안정화는 후속이며 보안 설정을 완화하지 않았다. 미로그인은 별도 브라우저에서 플랫폼 접근 거부, 앱 로그아웃 후에는 새 세션의 Google 로그인 요구를 확인했다. 다른 실제 계정과 장시간 만료는 단위 검사만 했으며 실계정 왕복 검증과 구분한다.

로컬 owner URL을 배포하지 않는다. 실제 앱에는 `xfolio_preview_app`, 시험 job에는 `xfolio_cloud_smoke`의 가상 표 SELECT/INSERT 권한만 사용한다. 접속 URL·OAuth·cookie 비밀은 Git 제외 `.streamlit/secrets.toml` 및 `.venv/`의 비밀 파일에 보관한다. `.env`는 기존 로컬 초기화용 owner 설정으로 유지한다.

## 3. Cloud Run용 이미지

Docker Engine이 켜진 환경에서 저장소 루트를 build context로 사용한다.

```powershell
docker build -f deploy/cloud/Dockerfile -t xfolio-cloud-smoke .
docker run --rm xfolio-cloud-smoke
```

두 번째 명령은 무통신 dry_run이어야 한다. `.dockerignore`는 허용한 파일만 포함하므로 `.env`·`.git`·로컬 DB·설정은 이미지에 넣지 않는다. 런타임은 일반 사용자로 실행한다. 이미지 크기·취약점·Linux 의존성과 잠금 파일 적용은 실제 빌드 후 확인한다.

## 4. GCP 단발성 배포

기존 `health-test` 프로젝트는 재사용하지 않는다. XFolio 전용 프로젝트·결제 계정·`us-central1` 리전·Artifact Registry 저장소를 계정 소유자가 확인한다. 리전은 현재 Neon 프로젝트의 실제 리전과 전송 비용도 비교한다. 서비스 사용·저장량·결제 설정을 확인한 뒤 아래 템플릿의 대문자 값을 교체한다.

1. Cloud Run·Artifact Registry·Secret Manager API를 활성화한다. 이번 단발성 시험에는 Scheduler 등록이 필요 없다.
2. 실제 이미지 `us-central1-docker.pkg.dev/PROJECT_ID/REPOSITORY/xfolio-smoke:TAG`를 만든다. 이미지 태그·digest와 총 보관 용량을 기록한다.
3. Secret Manager의 `xfolio-database-url`에 DB URL을 보관한다. 키를 shell 인자·명령 기록에 직접 쓰지 않는다.
4. 전용 실행 서비스 계정에 **해당 secret 하나의 읽기 권한만** 부여한다. Project Owner·Editor 같은 포괄 권한을 실행 계정에 부여하지 않는다.
5. 실행 수·timeout·재시도와 비용 통제를 확인하고 job을 만든다. schema는 위 DB 시험에서 미리 초기화한다.

```text
gcloud run jobs deploy xfolio-smoke
  --project PROJECT_ID
  --region us-central1
  --image us-central1-docker.pkg.dev/PROJECT_ID/REPOSITORY/xfolio-smoke:TAG
  --service-account xfolio-smoke@PROJECT_ID.iam.gserviceaccount.com
  --set-secrets XFOLIO_DATABASE_URL=xfolio-database-url:1
  --args=--run
  --tasks=1 --parallelism=1 --cpu=1 --memory=1Gi
  --task-timeout=60s --max-retries=0
```

위는 줄마다의 실행 명령이 아니라 옵션을 나눈 템플릿이다. 완성한 한 명령으로 실행한다. 처음에는 수동 실행해 성공·실패·로그의 비밀 비노출을 확인한다.

```text
gcloud run jobs execute xfolio-smoke --project PROJECT_ID --region us-central1 --wait
```

성공 로그와 실행 시간·메모리·DB 사용량을 [수행 기록](../../tasks/logs/2026-10-25_클라우드_전환_준비.md)에 추가한다. 실제 예약 작업 3종의 구현·시간대·중복·마감·백업 복원 시험이 끝나기 전에는 이 smoke를 운영 수집/게시 job으로 바꾸지 않는다. 이미지·secret·전송 등 무료 범위는 [비용 조사](../../docs/research/저장소와_관리자_화면.md#2026-10-25-무료-클라우드-전환-조사)를 참고한다.
