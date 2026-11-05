# 개인 뉴스레터 비공개 배포 준비

`deploy/cloud/`는 이전 시험 자산이며 이 폴더가 T05~T08 통합용 신규 구성이다. 현재는 로컬 구성 준비다. 실제 Lightsail/Neon 배포·Tailscale/OAuth·본인 기기 접근·아침 수신은 운영 인수 전이다. [계획](../../tasks/plans/비공개_뉴스레터_배포_준비.md) · [검증 계약](../../tasks/verification/integration/비공개_뉴스레터_배포_준비.md)

## 구성과 기본 실행

`본인 PC/휴대폰 → Tailscale Serve HTTPS → 호스트127.0.0.1:8088 → Caddy → React/API`다. API는 컨테이너 네트워크의8000에서만 받으며 DB 포트·worker 포트는 게시하지 않는다. worker는 같은 Python runtime 이미지의 별도 프로세스다. 기본 Compose에는 API와 web만 기동하고, `worker` profile을 선택해야 모의 예약이 시작된다.

```sh
# 저장소 루트, Docker Compose 2.24 이상. 비밀 파일 없이 문법만 확인 가능.
docker compose -f deploy/newsletter/compose.yaml config --quiet
docker compose -f deploy/newsletter/compose.yaml build api web
docker compose -f deploy/newsletter/compose.yaml up -d api web
# 준비 환경의 모의 예약. 실제 제공처 수집/Telegram 연결 완료를 뜻하지 않는다.
docker compose -f deploy/newsletter/compose.yaml --profile worker up -d worker
docker compose -f deploy/newsletter/compose.yaml stop worker
```

호스트는 Ubuntu Linux·Docker Engine·systemd-journald를 가정한다. Windows는 개발/정적 검사 환경이며 실제 운영과 다르다. journald driver를 쓰므로 Docker Desktop에서 컨테이너 기동 전 별도 시험용 logging override가 필요하다. `healthcheck`는 프로세스/정적 웹 응답만 확인한다. API의 DB·인증 준비 완료, worker의07:50/08:00 작업 성공을 health 상태로 대신 판정하지 않는다.

서버 비밀 파일은 저장소 밖 `/etc/xfolio/`에 `0600`으로 두고 아래 경로 변수만 지정한다. Compose에 값을 직접 넣거나 `config` 전체 결과를 공개 로그에 남기지 않는다. `api.env.example`·`worker.env.example`·`maintenance.env.example`을 참조한다. API에는 공급자/Telegram 비밀이 없고 worker에는 OAuth 비밀이 없다. 예시 값 그대로면 실제 연결할 수 없다.

```sh
export XFOLIO_API_ENV_FILE=/etc/xfolio/api.env
export XFOLIO_WORKER_ENV_FILE=/etc/xfolio/worker.env
export XFOLIO_MAINTENANCE_ENV_FILE=/etc/xfolio/maintenance.env
export XFOLIO_PG_SERVICE_FILE=/etc/xfolio/pg_service.conf
export XFOLIO_PGPASS_FILE=/etc/xfolio/pgpass
```

T06 진입점은 `python -m xfolio.jobs.worker`이며 기본 모의 실행이다. `--once`는 합성 무통신1회, `--schedule`은 기본 모의 예약이다. 이 구성은 `XFOLIO_WORKER_LIVE_ACCEPTED=false`를 고정하며 `--live`를 넣지 않는다. 실제 수집/예산원장/설정 고정 연결은11/5 구현·격리 검증했다. 실제 정시 수신·유료 요약·운영 인수 뒤 별도 검토한 운영 override로 live를 활성화한다. 오후14/16시는 T09 인수 전 기본OFF를 유지한다.

live 준비/예약에는 `worker.env.example`의 KIS/Finnhub/OpenAI 키와 `XFOLIO_GENERATION_LIMITS_FILE`이 필요하다. `GenerationLimits` JSON의 현재 단가·근거·timezone 포함 유효기간을 직접 검토한다([형식](../../README.md#t03-뉴스-수집공식-발표-요약)). env_file은 파일 내용을 컨테이너에 복사하지 않는다. 운영 override에서 호스트 `/etc/xfolio/generation_limits.json`을 `/run/secrets/generation_limits.json`으로 읽기 전용 bind mount하고 uid10001의 읽기 권한을 확인해야 한다. 이미지/Git에 넣지 않는다. 기본 Compose에는 이 mount와 live 활성화를 추가하지 않았다. worker는 `.env` 자동 로딩 없이 주입한 환경만 읽는다.

## 비공개 접속과 인증 인수

Lightsail의IPv4/IPv6 방화벽에80/443/8000/8088/5432를 인터넷 허용하지 않는다. Docker publish는 `127.0.0.1:8088` 한 건이다. 호스트 Tailscale에서 `tailscale serve --bg http://127.0.0.1:8088`로 tailnet HTTPS에 연결하고 `tailscale serve status`·`tailscale funnel status`로 경계를 확인한다. Funnel은 활성화하지 않는다. 현재 도구로 명령을 실행했다는 뜻이 아니다.

기본 tailnet 전체 허용을 그대로 본인 전용이라고 가정하지 않는다. 본인 계정·승인 PC/휴대폰만 관리자 대상에 접근하도록 ACL/grants를 검토한다. OAuth의 승인 redirect URI는 `https://SERVER.TAILNET.ts.net/api/auth/callback`, API의 `XFOLIO_PUBLIC_ORIGIN`도 같은 origin으로 설정한다. Google 세션·Secure/HttpOnly cookie·CSRF를 유지한다. PC/휴대폰의허용, 다른 계정·미등록기기·공인IP·IPv6 직접 접근 거절, 로그인 callback·설정 변경 CSRF를 실측한다.

## DB 역할과 migration

Neon의 운영 DB는 별도 생성/인수한 대상을 사용한다. API/worker/migration/maintenance/backup 자격을 분리한다. runtime 역할에는 DDL·role 생성 권한을 주지 않는다. API는 세션·감사/설정·관심목록 쓰기와 조회, worker는 수집/편성/outbox·예산원장 쓰기를 사용한다. maintenance는 보존 계약의 만료 행 삭제, backup은 필요한 읽기 권한만 가진다. 실제 역할별 GRANT 목록·RLS/부모 FK/trigger 권한은 최종0007 통합 schema에서 인수하며 이 구성은 권한을 생성하지 않는다.

신규0006/0007은 T05/T06 통합 뒤 단일head인지 확인한다. 실행 이미지에 `alembic.ini`·`migrations/`가 포함되지만 기동 명령은 migration을 자동 실행하지 않는다. 다음은 사전에 검토한 신규/격리 DB 또는 승인된 운영 적용 시에만 실행한다.

```sh
docker compose -f deploy/newsletter/compose.yaml --profile maintenance run --rm maintenance alembic heads
docker compose -f deploy/newsletter/compose.yaml --profile maintenance run --rm maintenance alembic upgrade head
```

기존 DB는 백업과 복원 시험 후0005→head 이행을 검증한다. 운영 downgrade로 데이터를 되돌리려 하지 말고 새 버전·forward fix·검토한 복구 중 선택한다. restore와 운영 DB는 같은 URL을 사용하지 않는다.

## 보존·정기 삭제·복원 gate

`maintenance.py plan`은 DB에 연결하지 않는다. `verify`는 명시한 유지보수 DB만 읽고, `purge --execute`만 만료 행을 삭제한다. 설정/발송 결과 metadata는365일, 가격/뉴스/편성·준비 snapshot은90일 또는 원본의 더 이른 만료를 따른다. `operations_events`에서는 `kind=newsletter_prepare`만90일 검사·삭제하며 다른kind의 보존을 변경하지 않는다. 삭제는 각 저장 서비스의 계약을 호출한다. 현재 singleton 설정은 삭제하지 않는다. 외부 DB에는 `sslmode=verify-full`을 요구하며 이미지의 시스템 CA 경로를 사용한다.

```sh
docker compose -f deploy/newsletter/compose.yaml --profile maintenance run --rm maintenance
docker compose -f deploy/newsletter/compose.yaml --profile maintenance run --rm maintenance python /app/deploy/newsletter/maintenance.py verify
docker compose -f deploy/newsletter/compose.yaml --profile maintenance run --rm maintenance python /app/deploy/newsletter/maintenance.py purge --execute
```

`can_resume=false` 또는 종료코드2이면 runtime 재개를 보류한다. 만료된 가격·편성/뉴스가0건이어야 한다. legacy 본문 테이블에 행이 남아 있으면 자동삭제하지 않고 gate를 차단하므로, 구버전 보관·이관·가격/근거 삭제 정책을 검토해야 한다. schema가 미완성이거나 DB 연결 실패면 종료코드1이다. URL·오류 원문·본문을 출력하지 않고 집계/고정 오류만 출력한다.

각 저장 서비스의 삭제는 개별 트랜잭션이다. 중간 장애면 이미 끝난 삭제를 되돌리지 않고 원인을 해결한 뒤 다시 실행·검사한다. 만료 조건 삭제는 반복할 수 있으며 전체 삭제가 하나의 원자 트랜잭션이라고 가정하지 않는다. `can_resume`는 이 도구의 보존 검사 결과이며 앱 기동을 기술적으로 잠그는 스위치는 아니다. 운영 절차에서 통과 전 API/worker를 재개하지 않아야 한다.

매일00:20 KST에 `purge --execute`와 뒤이은 `verify`를 systemd timer 등으로 실행하고 실패를 운영 로그에서 확인하도록 설치한다. 이 timer는 아직 설치하지 않았다. 90일 만료 행은 조회에서 즉시 차단하며 물리 삭제는 정기 작업으로 제거한다. 원문/근거는 이 신규 경로에서 영속 복제하지 않는다. 향후 원문을 별도 저장하면 최대7일 조건을 별도 인수해야 한다.

운영 로그는 journald에만 남기고 [journald-retention.conf](journald-retention.conf)를 `/etc/systemd/journald.conf.d/60-xfolio-retention.conf`에 설치해30일 상한을 적용한다. 이 설정은 호스트 전체 journal 보존에도 영향을 주므로 기존 호스트 정책을 검토한 뒤 설치한다. API access log를 꺼 callback query가 저장되지 않게 했으며 Caddy request log도 켜지 않았다. 재시작·설정 반영 후 journal 보존·디스크 상한을 확인한다. Docker json-file의크기 회전만으로30일을 보장하지 않는다.

## 백업과 복구

`pg_service.conf.example`의 서비스명·TLS·DB와 `pgpass.example`을 저장소 밖에 설치한다. Linux의 실제 두 파일은 실행uid10001 소유·0600이어야 한다. Compose bind secret은 uid/mode를 재매핑하지 않을 수 있으므로 호스트에서 권한을 맞춘다. 비밀번호를 명령 인수·프로세스 목록·로그에 넣지 않는다.

백업은 일시중지와 수집/발송 작업 종료 후 생성한다. `pg_dump` stdout을 `age`로 암호화하며 `backup` 컨테이너의 logging driver는 `none`이다. 평문 dump를 서버 파일/컨테이너 로그에 남기지 않는다. 다음 예시는Linux Bash·host age 설치 후 실행한다. 백업 파일 권한은0600으로 제한하고 암호화 키는별도 보관한다.

```sh
set -euo pipefail
umask 077
docker compose -f deploy/newsletter/compose.yaml stop worker
mkdir -p /var/lib/xfolio-backups
backup_path="/var/lib/xfolio-backups/$(date -u +%Y%m%dT%H%M%SZ).dump.age"
docker compose -f deploy/newsletter/compose.yaml --profile backup run --rm -T backup | age -r "$XFOLIO_BACKUP_AGE_RECIPIENT" > "$backup_path"
```

암호화도 보존 연장은 아니다. 백업은최대7일로 정리하고 백업 생성 전 만료 삭제를 실행한다. 이전 백업 안의 이미 만료된 자료는 복원 후 runtime에 노출하기 전에 반드시 제거한다. 실제 백업 매체·제공처 삭제 조건·복구주기/RPO/RTO·Neon 기본백업/PITR 보존 가능범위는 운영 개시 전에 확인한다. 앱 삭제가 제공처의PITR/스냅샷 즉시 삭제를 뜻하지 않는다.

복원은격리 DB로 수행한다. worker와 API를 중지하고 격리 DB URL을 maintenance에만 연결한다. 별도 `xfolio_restore` 서비스에 `age -d` 결과를 pipe해 `pg_restore --no-owner --no-acl --exit-on-error --dbname=service=xfolio_restore`로 복원한다. `--clean`이나 운영 DB URL은 쓰지 않는다. `purge --execute`→`verify`→migration/schema/권한 점검→모의 연결→안전한 재개 순서다. unknown/sending 발송을 복원했다고 자동 재송신하지 않는다. 실제 수신과 DB 상태가 어긋날 수 있으므로 T06 결과 불명 처리로 인수한다.

## 비용·운영 개시

월예산50,000원은서버·DB·백업/전송·AI의 합계로 재산정한다. Lightsail 선택요금·세금·환율·Neon 한도/유휴중단·Tailscale 개인플랜 조건·OpenAI 실제모델/단가·추가EBS/네트워크를 확인하고 기존 X 견적은재사용하지 않는다. 현재 구성은 가격/비용을 실측하지 않았으며 자원을 생성하지 않았다.

T07 전체 아침 흐름과 본인 실제 수신 이후 T08 운영 인수에서 PC/휴대폰 접근·공개차단·재부팅 worker/Serve 복구·정시 발송·삭제·암호화 백업/격리 복원을 검증한다. 이 문서의명령 제공은 실행 완료나 운영 개시 승인을 뜻하지 않는다.
