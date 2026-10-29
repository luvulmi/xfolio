# Google callback 등록과 실제 로그인·세션·로그아웃 검증

- 수행일: 2026-10-29, Asia/Seoul
- 요청: Google callback 등록과 실제 로그인 검증 대행. 저장 직전 추가 확인을 받은 뒤 실행
- 결과: 로컬 개발 환경의 실제 Google 로그인·세션 유지·로그아웃 검증 완료
- 관련: [검증 계약](../verification/Google_로그인_실제_검증.md) · [관측 메타데이터](../verification/assets/auth/google_login_20261029.json)

## 등록과 실제 확인

1. Chrome에서 기존 xfolio 프로젝트의 `xfolio-streamlit` 웹 클라이언트를 확인했다. 기존 Streamlit callback을 유지하며 `https://localhost:8443/api/auth/callback`을 추가했다. 사용자 승인 후 저장 성공 알림과 다시 연 URI 목록을 확인했다.
2. Google의 `redirect_uri_mismatch` 해소를 확인했다. Chrome의 자기서명 인증서 경고는 사용자가 직접 처리했다. OS 인증서 신뢰 저장소는 변경하지 않았다.
3. 21:54 KST경 실제 Google 로그인에서 로컬 허용 목록과 일치하는 계정을 선택하고 기존 XFolio 재로그인을 진행했다. callback의 코드 교환·ID token 검증·서버 세션 생성 뒤 운영자 대시보드가 열렸고 새로고침 후에도 유지됐다.
4. 로컬 PostgreSQL의 활성 허용 세션1개, 절대 만료12시간, 세션 payload에 Google ID/access token0개를 값 노출 없이 확인했다.
5. 실제 화면에서 로그아웃했다. 활성 세션0개와 새로고침 뒤 로그인 화면, 미인증 `/api/auth/me` 401을 확인했다. 최종 브라우저는 로그아웃 상태다.

이 결과는 모의 Google 시험이 아니다. 실제 비허용 계정 거절·자연 만료·운영 도메인 배포를 시험한 결과와는 구분한다. 자동 테스트의 쿠키/CSRF/만료 검사와 실제 계정 흐름을 함께 근거로 사용한다.

## 검증 중 발견한 HTTPS 결함

브라우저의 유휴 TCP preconnect가 TLS handshake를 시작하지 않으면 기존 HTTPS 서버의 수신 루프가 막혔다. 두 번째 정상 TLS 요청도 timeout이 되는 회귀 시험으로 재현했다.

`scripts/dev/local_https.py`에서 handshake를 연결별 작업 스레드로 옮기고 handshake5초·요청15초 제한을 적용했다. 인증서·TLS 최소 버전·검증은 유지했다. 같은 인증서와 주소로 서버를 재시작해 요청이 정상 처리되는지 확인했다.

- 관련 pytest: **9 passed**. 수정 전 새 회귀 시험은 TLS timeout으로 실패했다.
- 전체 Ruff check/format 통과(172파일). Authlib의 기존 `jose` 경고는 별도 후속이다.
- 변경 문서·JSON 18파일의 UTF-8/BOM·JSON 구문·상대 링크와 `git diff --check`를 검사해 통과했다.
- 화면 확인 PNG는 Git에서 제외한 `.cache`에만 저장했다. 저장소 결과에는 이메일·클라이언트 비밀·OAuth code/state·세션·CSRF 값을 남기지 않았다.

## 다음 작업

인증 검증 기록과 HTTPS 수정 사항을 검토하고 커밋한다. 이후 월 예산과 의미/길이 검증이 준비된 실자료 생성·reviewed 승인 정상 흐름을 연결한다. 이번 요청으로 X 게시·유료 모델 호출·AWS 배포를 수행하지 않았다.
