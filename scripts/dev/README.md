# 로컬 개발과 서비스 설정 도구

## Telegram 수신 대상 준비

`setup_telegram.py`는 [루트 설정 안내](../../README.md#telegram-알림-환경-설정-준비)에 따라 `@ringXFolioNotifyBot`을 검증하고 개인 대화의 수신 ID를 `.env`에 저장합니다. 기본은 무통신이며 `--run --save-chat`에서만 공식 Bot API 3회 조회와 로컬 저장을 수행합니다. 메시지 발송·webhook 변경·업데이트 확인 처리는 하지 않습니다. `tests/test_telegram_setup.py`에서 개인 대화 선택, 기존 설정 보호, 오류의 토큰 비노출을 외부 API 없이 검증합니다.

## 로컬 HTTPS와 Google 인증 연결 준비

이 도구는 개발용이다. HTTPS 프록시는 `127.0.0.1`에만 바인딩하고 빌드한 React와 `/api`를 같은 origin에서 제공한다. 인증서는 `.cache/dev_https/`에만 보관하며 OS 신뢰 저장소를 변경하지 않는다. 공개 배포는 별도 검증이 필요하다.

2026-10-29에는 기존 클라이언트의 callback 등록과 실제 허용 운영자의 로그인·새로고침 세션 유지·로그아웃을 로컬에서 확인했다. [실제 검증 결과](../../tasks/logs/2026-10-29_Google_callback과_로그인_검증.md). 이 도구 설명 자체를 다른 환경의 로그인·공개 배포 합격으로 해석하지 않는다.

## 실행

저장소 루트에서 `uv sync`, `npm --prefix frontend ci`, `npm --prefix frontend run build`를 먼저 수행한다. 터미널 1에 **별도로 만든 격리 API DB URL**을 `XFOLIO_API_DATABASE_URL`로 설정한다. 기존 가상 preview DB의 `XFOLIO_DATABASE_URL`을 복사하거나 자동 재사용하지 않는다. 새 DB의 migration은 루트 README의 절차를 따른다.

```powershell
uv run python scripts/dev/run_api.py --use-streamlit-auth
```

`--use-streamlit-auth`를 명시했을 때만 `.streamlit/secrets.toml`의 `auth.client_id`, `auth.client_secret`, `XFOLIO_ADMIN_EMAILS`를 메모리에서 재사용한다. 원래 redirect URI·cookie secret·DB URL·metadata URL은 재사용하지 않는다. 키·메일·접속 문자열을 출력하거나 새 설정 파일로 저장하지 않는다. 이 옵션을 생략하면 루트 README의 Google API 환경변수가 필요하다.

터미널 2에서 실행한다.

```powershell
uv run python scripts/dev/local_https.py
```

브라우저에서 `https://localhost:8443`으로 연다. 자기서명 개발 인증서이므로 브라우저 경고가 표시된다. 이 프로세스는 인증서를 OS에 설치하지 않는다. 인증서 파일만 준비하려면 `uv run python scripts/dev/local_https.py --cert-only`를 사용한다. 포트를 바꾸면 API 시작 시 `--origin https://localhost:새포트`와 proxy의 `--port 새포트`를 함께 바꾼다.

기본 프록시 대상은 `http://127.0.0.1:8000`이며 외부 호스트를 대상으로 지정할 수 없다. API access log와 HTTPS proxy request log를 끄므로 callback code/state·쿠키가 요청 로그에 남지 않는다. 기존 앱의 server-side 세션·CSRF·허용 운영자 검사를 그대로 사용한다. API 연결 실패는 502, 설정 미완료는 API의 503으로 표시한다.

## Google 콘솔에서 별도로 확인할 것

승인된 redirect URI에 `https://localhost:8443/api/auth/callback`이 등록돼야 한다. 실제 Google 콘솔의 redirect URI는 이 스크립트가 수정하지 않는다. 기존 Streamlit callback과 FastAPI callback은 경로가 다르므로 키가 같아도 자동 호환된다고 보지 않는다. Google OAuth 앱의 테스트 사용자·동의 화면·허용 계정도 실제 로그인 전에 확인해야 한다. URI 등록 후 실제 로그인으로 계정 허용/차단, 서버 세션, 만료, CSRF, 로그아웃을 확인해야 인증 이전 완료로 판정할 수 있다.

## 검증 범위

`tests/test_dev_https.py`는 인증서 SAN/재사용·`.cache` 제한, 외부 proxy 대상 차단, 인증서 검증을 켠 로컬 TLS, 유휴 TCP 연결과 다른 TLS 요청의 동시 처리, SPA 제공, API 쿠키/Origin/CSRF 전달과 명시적 키 재사용을 확인한다. 로컬 TLS 시험에는 Windows asyncio/socket 정책에 따라 샌드박스 밖 실행이 필요할 수 있다. 이 자동 시험은 실제 Google 인증 성공이나 실제 운영 DB 사용 성공을 뜻하지 않는다.

개인키는 인증서와 함께 Git 제외 경로에 남는다. 테스트와 브라우저는 해당 개발 인증서만 명시적으로 신뢰하도록 설정할 수 있으며, 시스템 전체 인증서 검증을 끄지 않는다. 종료는 각 터미널의 `Ctrl+C`로 수행한다.
