# Google callback 등록과 실제 로그인 검증

- 기준일: 2026-10-29, Asia/Seoul
- 상태: callback 등록·실제 Google 로그인·세션 유지·로그아웃 검증 완료. 최종 브라우저 상태는 로그아웃
- 요청: 기존 Google OAuth 클라이언트에 callback을 등록하고 실제 로그인 검증
- 관련: [로컬 HTTPS 도구](../../../scripts/dev/README.md) · [기존 통합 결과](../../logs/2026-10-28_통합_검증과_실자료_연결.md)

## 대상과 완료 조건

기존 `xfolio-streamlit` 웹 클라이언트에 `https://localhost:8443/api/auth/callback`을 추가한다. 기존 Streamlit callback을 보존하고 scope·운영자·client secret을 변경하지 않는다. 저장된 URI를 콘솔에서 확인하고 실제 Google 흐름으로 callback→서버 세션→인증 조회→로그아웃 후401을 검증한다. 비밀·인증 code/state·세션/CSRF 토큰·운영자 이메일을 결과 파일에 남기지 않는다.

## 확인한 사실

- 로컬 HTTPS 정적 화면 HTTP200·미인증 API401. OS 신뢰 저장소를 변경하지 않고 개발 인증서를 명시적으로 검증했다.
- Chrome에서 기존 xfolio 프로젝트와 `xfolio-streamlit` 웹 클라이언트를 찾았다. 로컬 설정에서 사용하는 클라이언트와 일치한다.
- 콘솔의 승인된 리디렉션 URI는 기존 Streamlit 주소 한 개였다. 사용자 저장 승인 후 항목 2의 `https://localhost:8443/api/auth/callback`을 저장했다. 콘솔의 저장 성공 알림과 다시 연 클라이언트의 URI 두 개를 확인했다.
- 처음 Chrome의 로컬 로그인 주소 접근은 `ERR_CERT_AUTHORITY_INVALID`로 중단됐다. 이후 사용자가 인증서 경고를 직접 확인했다.
- 저장 뒤 실제 Google 인증 시작 요청에서 `redirect_uri_mismatch`가 없어졌다. Google 시작 단계 통과이며 사용자 계정 로그인·토큰 교환 성공을 뜻하지 않는다.
- 이후 사용자가 인증서 경고를 직접 확인했고, 실제 Google 계정 선택·기존 XFolio 재로그인 계속을 거쳐 운영자 대시보드에 도착했다. Google provider 대역을 사용하지 않았다.
- 새로고침 뒤에도 인증 화면이 유지됐다. 로컬 PostgreSQL에서 허용 운영자 세션1개·절대 만료12시간·세션 payload의 공급자 토큰0개를 확인했다. 비밀 값은 출력하지 않았다.
- 실제 UI 로그아웃 뒤 DB 활성 세션0개, 새로고침 뒤 로그인 화면, 미인증 `/api/auth/me` HTTP401을 확인했다. [비밀 없는 관측 메타데이터](../assets/auth/google_login_20261029.json)

## 로컬 HTTPS 지연 수정

인증서 확인 중 열린 유휴 TCP 연결이 TLS 수신 루프를 막아 다른 요청도 handshake timeout이 되는 결함을 발견했다. 유휴 연결을 유지한 채 두 번째 정상 TLS 요청을 보내는 회귀 시험에서 실패를 재현했다.

`scripts/dev/local_https.py`에서 TLS handshake를 연결별 작업 스레드로 옮기고 5초 handshake·15초 요청 제한을 적용했다. 인증서·암호화 검증·OS 신뢰 설정은 바꾸지 않았다. 관련 시험 9건이 통과했고 같은 인증서로 서버 재시작 후 HTTPS200·Google 시작 오류 없음까지 확인했다. 원래 Streamlit callback은 유지됐다.

- 브라우저 보안 경고·계정 추가 인증이 발생하면 사용자가 해당 단계를 수행해야 한다. 등록된 주소와 로그인 결과가 확인되기 전 완료로 표시하지 않는다.

## 진행

- [x] 기존 callback과 추가 URI 확인
- [x] 등록 저장과 저장 후 표시 확인
- [x] 실제 Google 로그인·허용 운영자·세션 검증
- [x] 로그아웃·미인증401 재확인

실제 비허용 Google 계정의 거절, 자연 경과한 유휴/절대 만료, 운영 도메인/AWS 로그인은 이번 수동 시험 범위가 아니다. 세션 만료·CSRF·쿠키 플래그의 기존 자동 시험과 이번 실제 로그인 결과를 구분한다. [수행 기록](../../logs/2026-10-29_Google_callback과_로그인_검증.md)

인증서·OAuth 응답·세션을 흉내 낸 로그인 성공으로 대체하지 않는다. X·Telegram·유료 모델·운영 DB는 이 검증에 사용하지 않는다.
