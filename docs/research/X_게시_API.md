# X 게시 API와 개발자 설정 가이드

- 갱신: 2026-10-30, Asia/Seoul · 준비 마감: **2026-11-01(일)**
- 확인 범위: X 공식 등록·앱·콘솔·게시·요금 문서. 계정 로그인·앱 생성·키 발급·충전·실제 API 호출은 하지 않았다.
- 사용자 확인: **게시 계정 `@ringXFolioBot` 확정, 콘솔에 본인 계정용 읽기 및 쓰기 토큰 표시, OAuth 1.0a 키·토큰 4개 별도 보관 완료**. 실제 API 인증·서버 연결은 미검증이다.
- 현재 기준: [운영 정책](../운영_정책.md) · [월 비용](월_비용.md) · [X 게시 작업](../../tasks/plans/X_게시.md)

## 먼저 준비할 것

**게시할 X 계정으로 콘솔 가입 → 앱 생성 → 쓰기 권한 설정 → 사용자 토큰 보관 → 이용 요금 확인** 순서로 진행한다. 키 발급과 실제 게시 검증은 별개다.

단일 본인 계정의 초기 준비에는 **OAuth 1.0a 사용자 인증을 추천**한다. 공식 콘솔에서 앱 소유자의 Access Token/Secret을 직접 발급받을 수 있어 별도 사용자 동의 화면 구현 없이 시작하기 쉽다. 설정 추천이며 제품의 인증 방식 확정이나 연동 완료는 아니다.

## 게시 계정

사용 계정은 **@ringXFolioBot**으로 확정했다. 프로필 소개의 수정 예시는 다음과 같으며 실제 계정에는 적용하지 않았다.

> SPY·QQQ·DIA ETF 종가와 미국 시장 주요 뉴스를 한국어로 정리합니다. 출처와 기준 시각을 담는 비상업 정보 공유 프로젝트입니다.

## 개발자 콘솔 설정 순서

공식 문서 기준 절차다. 실제 계정의 콘솔 화면과 메뉴 명칭은 다를 수 있다.

### 1. 게시할 계정으로 개발자 등록

1. [X Developer Console](https://console.x.com/)에 접속한다.
2. **XFolio 글을 게시할 X 계정**으로 로그인했는지 확인한다. 콘솔에서 직접 발급하는 본인용 토큰은 앱 소유자 계정을 나타낸다.
3. 개발자 약관·정책을 읽고 사용 목적과 필요한 프로필 정보를 사실대로 작성한다.

사용 목적 영문 초안은 아래와 같다. 실제 운영 계획과 폼의 질문에 맞춰 수정한다.

> I am building XFolio, a personal project that publishes Korean-language briefings about SPY, QQQ, and DIA ETF closing prices, major US market news, and BLS CPI releases. These source materials are collected outside X. I plan to use the X API to publish up to four original posts once each morning to my own account after human review and approval, and to check the status of my own published posts when needed. I do not plan to collect other users' posts or send unsolicited replies or direct messages. X content will not be used to train AI models.

### 2. XFolio 앱 생성

- 대시보드의 **New App / Create App**에서 앱을 만든다.
- 앱 이름 추천: **XFolio**. 이미 사용 중이면 **XFolio Brief KR** 등으로 구분한다.
- 설명 예시: **Human-reviewed Korean briefings on US markets and official economic releases.**
- Website URL을 요구하면 실제 공개 프로젝트 소개 페이지 또는 공개 GitHub repository 주소를 사용한다. 앱 이름은 X의 표시 이름·아이디와 별개다.

### 3. 사용자 인증과 쓰기 권한 설정

앱의 인증·권한 설정에서 **OAuth 1.0a의 Read and write**를 선택한다. Read only로는 게시할 수 없다. 현재 기능에는 DM 권한이 필요하지 않다.

권한을 먼저 저장한 뒤 본인용 Access Token/Secret을 발급한다. **읽기 전용 상태에서 토큰을 먼저 만들었다면 권한 변경 후 새 권한의 토큰을 다시 발급**한다. 기존 토큰이 자동으로 쓰기 권한을 얻는다고 가정하지 않는다.

OAuth 2.0의 앱 유형·callback 설정 화면까지 진행한다면 아래 인증 비교를 참고한다. 현재 XFolio에는 X용 callback이 구현되어 있지 않다. 콘솔이 필수 callback을 요구하는 경우 X 인증 경로를 먼저 정하고, 기존 Google 로그인 callback이나 임의의 서비스 주소를 재사용하지 않는다.

### 4. 키·사용자 토큰 4개 보관

앱의 키·토큰 관리 화면에서 다음을 발급하고 비밀번호 관리자 등 안전한 곳에 보관한다. 공식 문서는 발급 시 한 번만 표시되며 재발급하면 기존 값이 무효화된다고 안내한다.

| 자격 정보 | 역할 |
| --- | --- |
| API Key | 앱 식별·OAuth 1.0a 요청 서명 |
| API Key Secret | 앱 비밀 값·요청 서명 |
| Access Token | 본인 게시 계정의 사용자 인증 |
| Access Token Secret | 사용자 인증 요청 서명 |

**API Key만으로 게시할 수 없다.** 콘솔의 App-only Bearer Token은 위 사용자 인증을 대신하지 않는다. OAuth 2.0에서 동의 후 얻는 사용자 Access Token과도 구분한다.

키 값은 채팅·발표 자료·GitHub·React 코드에 넣지 않는다. 루트 `.env`에 `X_API_KEY`, `X_API_KEY_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`을 설정하고 `uv run --env-file .env ...`로 서버 프로세스에 전달한다. [입력·무통신 확인 명령](../../README.md#x-인증-환경-설정-준비)을 따른다. `.env.example`에는 빈 항목만 두었다. X 전송 어댑터는 아직 미구현이며 환경 전달만으로 게시가 동작하는 것은 아니다.

### 5. 요금·잔액·지출 상한 확인

현재 공식 안내는 **선불 크레딧을 충전해 쓰는 사용량 과금**이다. 최종 적용 단가와 충전 조건은 자신의 콘솔에서 확인한다.

| 항목 | 2026-10-30 공식 공개 단가 |
| --- | ---: |
| 일반 글 생성 | $0.015 / 요청 |
| URL 포함 글 생성 | **$0.200 / 요청** |
| 일반 Post 읽기 | $0.005 / 리소스 |

뉴스는 원문 URL을 포함하므로 링크 글 단가를 적용한다. 하루 ETF 1글+뉴스 최대 3글의 산식·출처 URL 유무별 비용과 월 50,000원 상한 차이는 [월 비용](월_비용.md)에서 관리한다.

초기 시험은 **자동 충전을 끄고 작은 지출 상한을 설정하는 안을 추천**한다. 예를 들어 콘솔이 허용하면 시험용 $2 상한을 검토할 수 있지만, 이는 최소 충전액이나 승인된 결제 금액이 아니다. 준비 단계에서 단가·잔액·상한 설정 여부를 기록하고 충전 완료와 구분한다.

### 6. 11/1 준비 완료 여부 기록

- [x] X 계정 보유·아이디 `@ringXFolioBot` 확정 — 사용자 확인.
- [x] 개발자 콘솔의 기존 기본 앱 사용 — 사용자 제공 설정 화면 기준.
- [x] Read and write와 본인 게시 계정 확인 — 사용자 제공 화면 기준.
- [x] API Key/Secret + Access Token/Secret 보관 — 사용자 완료 보고.
- [x] X 환경 변수 4개 로딩 확인. `--env-file .env`의 새 프로세스에서 `X_ENV_READY (presence only)`를 확인했다. 실제 API 인증·게시 성공은 미검증이다.
- [x] 실제 콘솔 잔액·지출 상한·자동 충전 상태 확인 — 10/30 잔액·지출 US$0.00, 한도 무제한, 결제 수단 없어 자동 충전 불가. [진행 기록](../../tasks/logs/2026-10-30_11월_1일_서비스_준비.md). 개별 endpoint 단가의 콘솔 대조는 후속.

확인 기록에는 계정 아이디·앱 이름·권한·발급 완료 여부만 남기고 비밀 값은 남기지 않는다. **이 목록은 설정 준비 기준이다.** 실제 인증 성공과 게시 성공은 후속 연동 시험에서 별도로 검증한다.

## 인증 방식 비교

| 방식 | 준비·구현 | 현재 판단 |
| --- | --- | --- |
| OAuth 1.0a 사용자 인증 | 위 4개 자격 정보와 요청 서명 | 본인 1계정의 초기 설정 추천 |
| OAuth 2.0 Authorization Code + PKCE | Client ID, 서버 유형이면 Client Secret, 동의·callback·갱신. tweet.read, tweet.write, users.read, 예약 운영용 offline.access 검토 | 세분화된 권한이 필요할 때 검토. 구현 방식 미확정 |
| App-only Bearer | 공개 데이터 읽기용 앱 토큰 | 사용자 게시 인증으로 사용 불가 |

공식 Apps 문서는 새 프로젝트에 OAuth 2.0을 권장하며, 게시 API와 Integration guide는 사용자 인증으로 OAuth 1.0a도 안내한다. XFolio의 초기 추천은 본인용 토큰 발급의 단순함을 기준으로 했다.

OAuth 2.0을 택하면 서버에서 비밀을 보관하는 **Automated App / Bot 또는 Web App** 유형을 검토한다. callback은 등록값과 실제 구현이 정확히 일치해야 하며 운영은 HTTPS, 로컬은 공식 안내의 http://127.0.0.1을 기준으로 한다. X callback·동의·갱신 코드는 후속 구현 대상이다.

## 실제 연동 때 검증할 것

- 게시 endpoint는 **POST https://api.x.com/2/tweets**다. 성공 **201**과 **data.id**를 승인 버전·본문·시각·시도 기록에 연결한다. 정상 응답에서 ID를 받았다면 추가 GET 없이 저장할 수 있다.
- 기본 가중 글자 수는 280이다. 한글·URL 계산은 Python len() 대신 공식 twitter-text 규칙과 대조한다. 기존 길이 계산은 [이전 조사](../archive/X_게시_API_조사_이력.md)에 보존했으며 실제 게시 성공 근거가 아니다.
- **2026-10-30 Integration guide는 셀프서비스 API 답글에 원문 작성자의 멘션/인용 조건, 글당 cashtag 1개 제한을 명시한다.** 본인 글에 이어 쓰는 스레드의 적용·예외는 이번에 확정하지 않았다. 답글 연결은 콘솔 조건과 후속 시험으로 확인하며 무조건 가능하다고 가정하지 않는다.
- 호출 제한은 무료 사용량과 다르다. [전용 제한 문서](https://docs.x.com/x-api/fundamentals/rate-limits)와 실제 응답 헤더를 확인한다.
- 모의 전송으로 승인·한도·중복·타임아웃·부분 성공·불명 결과를 먼저 검증한다. 불명 결과에서 자동 재전송하지 않는다. 자기 타임라인 대조도 과금될 수 있고 검색 실패만으로 미게시를 확정할 수 없다.
- 실제 공개 시험은 대상 계정·게시문·비용을 정하고 사용자의 명시적 게시 승인 후 진행한다. 이번 안내에서 실제 게시나 유료 호출은 하지 않았다.

## 공식 근거와 조사 이력

- [Getting Access](https://docs.x.com/x-api/getting-started/getting-access): 콘솔 가입·앱 생성·본인용 토큰·보관.
- [Apps](https://docs.x.com/fundamentals/developer-apps): Read and write·권한 변경 후 토큰·앱 유형·callback.
- [Developer Console](https://docs.x.com/fundamentals/developer-portal): 앱·키·사용량·크레딧 관리.
- [Create Post](https://docs.x.com/x-api/posts/create-post) · [Integration guide](https://docs.x.com/x-api/posts/manage-tweets/integrate): 게시 endpoint·사용자 인증·생성 제한.
- [Pricing](https://docs.x.com/x-api/getting-started/pricing): 선불 사용량 과금·URL 단가·자동 충전·지출 상한.
- [OAuth 2.0 PKCE](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code) · [Counting Characters](https://docs.x.com/fundamentals/counting-characters): 구현 참고. 세부 기존 조사는 10/22 기준이며 이번에는 두 문서 전문을 재확인하지 않았다.
- [2026-10-22 조사 보존본](../archive/X_게시_API_조사_이력.md): 이전 9글 편성·월 3만 원 예산·출처 통합 길이 계산. 현재 운영 기준으로 사용하지 않는다.
