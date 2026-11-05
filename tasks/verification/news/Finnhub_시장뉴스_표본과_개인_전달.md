# Finnhub 시장뉴스 표본과 개인 전달 조건

- 작성·실측: 2026-11-02 / 후속 검증·선정 반영: 2026-11-03, Asia/Seoul.
- 현재 상태: **본인 개인용 채택 / 이메일 확인 필수 아님 / 운영 기술 검증은 후속**. 11/2 23:41·23:54 KST 인증 응답을 관측했다.
- 요청: 무료 시장뉴스의 미국 뉴스 관련성·최신성 확인 후 본인 Telegram 전달·보관 조건 확인.
- 범위: 개발용 최소 조회·조건 조사·선정 상태의 문서 반영. 운영 채택·유료 구독·실제 Telegram 송신·공급자 문의 발송은 수행하지 않았다.

## 현재 기술 상태 · 11/3 링크 보완과11/4 관측 예약

- 제품 기본은 **월~금 중 한국 거래일08:00 아침1회·한국 휴장 평일/주말 미발송**(11/4 변경),14/16시 모두 선택·기본꺼짐이다.
- 공급자 직접 기사주소는 매체·HTTPS·허용 호스트·개별 기사 경로를 확인하면 채택하고 HEAD2xx를 필수로 요구하지 않는다. Google 경유만 정상 HEAD redirect로 같은 원매체의 개별 기사주소를 확인한다. 홈페이지/섹션/중간 페이지·임의 호스트·위험 주소는 제외한다.
- `provider_direct_url`/`publisher_redirect_url`은 주소 식별 결과이며 **원문 열람 성공이 아니다**. `article_availability_verified:false`를 유지한다. Google 비공식 해독·내부 RPC·본문 수집·차단 우회는 사용하지 않는다.
- 11/3 22:00:34.966~36.009 KST 실제 API1회·100건→제목 관련9건→직접 기사주소3건 선정. 처리한 Google 중간 페이지1건은 제외했고 HEAD2회였다. ID8712147/8711622/8711518을 선정했다. [집계](../assets/news_samples/finnhub_links_2026-11-03/metadata.json) · [보존 범위](../assets/news_samples/finnhub_links_2026-11-03/README.md).
- 무통신 링크/신선도44건·슬롯14건 합계58건을 검증했다. 직접 주소 무통신·출처/경로 거절·Google 경유/실패·예산 소진 후 직접 주소·잘못된 발행시각·24/96h·정시/지각·중복claim·오류 비밀 제거·프로브 통합을 검사한다.
- 이 밤 표본은08:00 관측이 아니다. 신선도 집계 추가 전 실제 증거여서 새 필드를 사후 추정해 넣지 않는다.

### 11/4 08:00 실제 관측 계약

| 항목 | 기준 |
| --- | --- |
| 예약 | Codex 이 대화의1회 자동화 `finnhub-08-1`, 11/4 07:59 KST 시작 후 슬롯 대기 |
| 정시 | 실제 Finnhub API 요청 시작11/4 08:00:00~08:00:59 KST만 인정 |
| 대기/지각 | 슬롯 전 최대90초만 대기. 너무 이르면 통신하지 않음. 08:01 이후는 누락/지각 기록·소급 조회 금지 |
| 호출 한도 | API1회·Google HEAD 최대12회, 최대3건 선정. 실제 송신 없음 |
| 기록 | 요청/응답/완료 실제 시각·발행시각 집계·24/96시간·후보/제외 사유·직접/Google 상태·선정 ID |
| 중복 | `metadata.claim`과 결과 파일로 같은 슬롯 재실행 방지, 덮어쓰기 금지 |
| 실패 | 네트워크/권한·앱 지연·실행 누락은 실패로 기록. 실패 claim을 지우고 재시도해 성공처럼 만들지 않음 |
| 실행 조건 | 로컬 PC가 켜져 있고 절전하지 않으며 Codex 앱과 프로젝트/.env가 사용 가능해야 함 |
| 현재 판정 | **예약/무통신 모의 검증 완료, 실제 정시 관측 미실행** |

```powershell
# 지금은 무통신 계획 확인만 수행한다.
uv run python scripts/experiments/finnhub_slot_probe.py --slot 2026-11-04T08:00:00+09:00 --output tasks/verification/assets/news_samples/finnhub_slot_2026-11-04_0800/metadata.json
# 예약 시각의 실행에는 --live를 추가한다. 과거 날짜를 바꿔 소급 인정하지 않는다.
```

`run_probe()`는 실제 응답 확보 시각 기준 신선도를 계산한다. 미래 값은 별도 집계하고 bool/문자열/NaN/Inf/음수/범위초과 timestamp는 무효로 처리한다. 발행 후 경과시간을 공급자 최초 수록 지연으로 해석하지 않는다. 이1회 관측은 시장 전체 회수율·매일3건 확보·운영 worker/본인 실제 수신 성공을 보장하지 않는다. [로컬 자동화 실행 조건](https://learn.chatgpt.com/docs/automations).

아래11/2 초기 검토의 HEAD2xx 필수/통과0건은 당시 코드/표본의 이력이며 현재 직접 주소 채택 기준과 구분한다.

## 11/3 현재 결정 · 이전 회신 대기 기준 대체

사용자는 본인만 개인 이용하고 제3자에게 제공하지 않으므로 별도 이메일 확인 없이 진행하기로 했다. Finnhub 개인 이용 조항을 비상업·비전문 본인1명 범위에 적용하고 회신을 자동 전송/보관의 필수 조건에서 제외한다. 기사 원제·매체·시각·링크만 표시하며 본문·이미지·AI 입력은 제외한다. 메타데이터90일은 제품 상한·더 엄격한 조건 우선이며 이용 종료 시 DB/캐시/백업 삭제와 Telegram 과거 메시지의 본인 수동 삭제 절차를 둔다. 타인 수신·공개·사업용 확대 시 조건을 재검토한다.

이는 프로젝트의 개인 이용 해석이며 공급자 개별 허가/회신을 취득했다는 뜻은 아니다. 아래 공개 문서의 명시 범위·실측 사실과 이전 검토는 이력으로 보존한다. **아래의 회신 전 비활성/추가 확인 권고는 이 후속 결정으로 대체됐으며 현재 필수 조건이 아니다.** 원매체 링크·실제08:00·worker/수신자/중복/전송 기술 인수는 그대로 남는다. 문의 문안은 필요할 때 쓸 선택 참고용이며 미발송이다.

## 준비와 안전한 인증

1. 본인이 [공식 회원가입](https://finnhub.io/register)에서 무료 계정을 만든다. 가입/약관 동의는 본인이 진행한다.
2. 로그인 후 계정 대시보드의 API Key를 확인한다. 요금표는 무료 $0/month·60 calls/minute·Personal Use를 표시한다. 카드/유료 구독은 이번 시험에 필요하지 않다.
3. 저장소 루트의 기존 `.env`에 `FINNHUB_API_KEY=본인키`를 추가한다. 채팅·발표·Git에는 키를 넣지 않는다. `.env.example`은 빈 이름만 기록한다.
4. 준비 후 “키 저장 완료”라고 알려주면 인증 시장뉴스1회부터 실행한다. 계정 화면의 예제 키나 다른 사람 키를 대체 사용하지 않는다.

최초에는 설정이 없었고 사용자가 이후 “키 저장 완료”라고 알렸다. 루트 `.env`의 키로 인증했고 값은 출력/증거 파일에 기록하지 않았다. 다른 계정/브라우저 비밀 저장소는 조회하지 않았다.

## 최소 표본 절차와 판정

- 공식 계약: `GET https://finnhub.io/api/v1/news`, `category=general`, 최초 `minId=0`. 서버에서만 인증하고 에러에 키·전체 요청 URL을 출력하지 않는다.
- 첫 인증 조회1회 후 응답 상태·기사 수·제목·출처·발행 Unix timestamp·원문 URL·기사ID를 대조한다. API 응답과 웹 문서의 예시를 구분한다.
- 응답 중 우선 최근10건을 검토해 미국 시장/금리/물가/미국 기업과 관련, 기타시장, 암호화폐 등으로 나눈다. 관련성 판정은 이 표본에 한정하며 시장 전체 회수율로 확대하지 않는다.
- 최대3건 후보에 대해 출처·원문 URL·시각 유효성·동일사건/ID 중복을 확인한다. URL의 존재나 정상 응답이 기사 이용권을 의미하지 않는다.
- UTC/KST를 함께 표시하고 실제 조회시각과 발행시각의 차이를 계산한다. API가 수집한 시각이 없으면 그 차이를 제공처 전달 지연으로 단정하지 않는다. 미래 시각/시각 누락도 구분한다.
- 한국 거래일08:00 편성에 적용할 때24시간과 미전달 최대96시간 창을 따로 대조한다. 월요일·미국 휴장에는 금요일 기사가 오래됐다는 이유만으로 제공처 장애로 판정하지 않는다.
- 적격0건·API권한오류·제공처실패를 구분한다. 첫 응답 실패 시 유료 endpoint나 다른 제공처로 자동 우회하지 않는다.
- 제목·링크 방식의 검증이며 본문/이미지 수집·일반 기사 AI 요약·Telegram 전송은 하지 않는다. 영속 보관은 허용 범위 확정 후 정하며, 원시 JSON 전문을 Git 증거로 남기지 않는다.

## 개인 전달·보관 · 공식 근거

확인한 [Finnhub 약관](https://finnhub.io/terms-of-service)의 Personal Use는 개인 비상업 이용의 근거다. 사업용·증권 전문직 등 개인 플랜 부적격 조건도 있으므로 계정 신청 시 확인한다. 제3자에게 데이터나 파생 결과를 공유/재배포하려면 서면 승인을 요구한다. 구독 데이터 이용 종료 시 해당 데이터 삭제를 요구한다.

**확인 사실:** 개인 이용 근거, 타인/제3자 공유 제한, 종료 시 삭제 의무.

**미확인 적용:** 본인 AWS 프로그램→본인1명 Telegram 전달이 개인 이용에 해당하는지, Telegram 경유의 취급, 자체 DB의 제목/URL/발행시각·발송 이력90일 보관 범위. 본인 알림을 타인 재배포라고 단정하거나 모든 개인 이용에 서면 승인이 필수라고 표시하지 않는다. 일정 기간의 명시 제한을 찾지 못했다고 무제한 저장을 허용하지 않는다. 공급자 문의 회신은 아직 없다.

공식 공개 약관 검토를 마쳤지만 구체적 개인 전달·보관 조건 인수를 완료한 것은 아니다. 약관이나 회신이 명확히 허용하는 범위가 있으면 그 근거로 판단하고 동일 용도의 별도 승인 절차를 중복 요구하지 않는다.

## 확인 문의 문안 · 미발송

공식 요금표에 안내된 `support@finnhub.io`에 적용 범위를 확인할 수 있다. 이번 요청은 조건 조사이며 문의 발송을 명시 요청한 것으로 확대하지 않았다.

> I am building a non-commercial application for my own personal use. I plan to query the general market-news endpoint one to three times per weekday and send up to three original headlines, publisher names, publication times and original article URLs to my own private Telegram chat. There are no other recipients, groups, public channels, customers or public data displays. I will not copy article bodies or images, or use the articles for AI summaries. The program runs on my own AWS instance. May I use the Free plan for this purpose and retain only headline/URL/publication metadata and delivery records in my private database for up to 90 days, deleting the relevant data when my access ends? Please clarify whether this is covered by personal use or requires separate written approval, and whether additional publisher-specific conditions apply.

후속 확인 문장도 함께 보낸다. DB·백업과 Telegram의 보존/삭제를 한 문제로 뭉뚱그리지 않는다.

> Processing is on AWS Lightsail, with my private PostgreSQL database hosted on Neon. No other person can access the application or data. Please also clarify permitted caching and backup retention, any publisher-specific headline/link restrictions, and deletion requirements when data access or my subscription ends. Telegram's standard Bot API generally cannot delete messages older than 48 hours. Is retaining these messages in my own private chat covered by personal use, and if deletion is required at termination, would deletion by me using the Telegram client satisfy that requirement?

## 실제 결과

### 인증·최신성

| 확인 항목 | 실제 결과 |
| --- | --- |
| 요청 | `category=general`, `minId=0` · HTTP200 · 1회 성공 |
| 실제 조회 | 2026-11-02 23:41:30~31 KST, 0.979초 |
| 반환 | 100건, 시각/URL 문법 오류0·미래시각0·ID/URL 중복0 |
| 최신 발행 | 11/2 23:03:44 KST, 조회보다 약38분 전 |
| 최과거 발행 | 10/30 16:25:07 KST |
| 최근24h/96h | 32건 / 100건 |
| 링크 도메인 | `www.cnbc.com`20건, `news.google.com`80건 |

제한 환경에서는 연결 오류로 HTTP 응답을 받지 못했고 네트워크 권한을 적용해1회 성공했다. 같은 성공 응답을 분석했으며 무료 계정의 모든 endpoint 권한을 검증한 것은 아니다. [집계 메타데이터](../assets/news_samples/finnhub_2026-11-02T144130Z/metadata.json)와 [보존 범위](../assets/news_samples/finnhub_2026-11-02T144130Z/README.md)를 남겼다.

이는 기사 발행 후 경과시간이다. Finnhub가 원문을 수집한 시각이 없으므로 실제 제공 지연38분 또는 매번38분 이내라는 뜻이 아니다. 링크 문법 검사는 원문 접근 가능·무료 열람·재사용 권한 검증이 아니다. 뉴스 본문/이미지는 열람·저장하지 않았다.

### 최신10건 관련성 · 제목 기준 개발 검토

아래는 표본 선정 판단이며 기사의 사실 확인·AI 본문 요약·투자 판단이 아니다. 원제/원시 JSON은 증거 파일에 복제하지 않고 검토 주제·ID만 남긴다.

| 분류 | 수 | 기사ID·검토 주제 |
| --- | ---: | --- |
| 미국 기업/시장 직접 관련 | 4 | 8711195 미국 기업 AI 자금조달, 8711197 미국 지수선물, 8710666 미국 중간선거/경제심리, 8710980 미국 중간선거/업종 |
| 국제 에너지·정세·간접 배경 | 3 | 8710450 중동 협상, 8711196 유럽 에너지기업, 8709512 아시아 원유 수입 |
| 초기 후보 제외 | 3 | 8711194 투자 의견형 콘텐츠, 8710557 중국 외교, 8710239 지역 경보 |

직접 관련4건 중 중간선거2건은 같은 사건군으로 묶으면3개 후보 주제가 남는다. 자금조달·미국 선물·중간선거 업종을 후보로 검토할 수 있으나, 선물/중간선거 기사는 Google News 경유 링크여서 개별 원매체 URL 검증 전 최종 적격으로 표시하지 않는다. 유료 구독 전용 여부도 경로만으로 확정하지 않았다.

### 08:00 적용 한계와 판정

현재100건 중 11/2 08:00 이전24시간 발행분15건, 이전96시간74건, 08:00 이후 발행분26건이다. **밤23:41 응답을 발행시각으로 거른 사후 계산**이며 실제08:00 API 응답을 관측/복원한 결과가 아니다. 08:00 정시 확보를 인수하려면 별도 시각 관측이 필요하다.

판정: 미국 관련 뉴스의 소량 개발 입력으로 기술적 가능성을 확인했다. `general`은 미국 주식 전용 필터가 아니므로 지역/기업/사건·중복 선정과 원문 링크 정규화가 필요하다. 최신100건의 단일 응답이며 전체 시장 누락률이나24시간 모든 기사 확보를 보장하지 않는다. 종목별 뉴스가 필요하면 회사뉴스를 별도 검토하되 이번에는 추가 인증 호출하지 않았다.

공식 약관은 재확인했으나 개인 Telegram/클라우드/90일 보관에 대한 개별 회신은 받지 않았다. 실제 Telegram·유료 endpoint/구독·문의 발송·계정 생성은 수행하지 않았다. 다음은 원문 링크 확인·허용 조건 인수·아침 관측이다.

[전환 작업](../../plans/개인용_뉴스레터_전환.md) · [이용 조건](../../../docs/research/데이터_이용_조건.md) · [시장뉴스 문서](https://finnhub.io/docs/api/market-news) · [요금표](https://finnhub.io/pricing)

## 23:54 KST 후속 · 필터와 정상 경유 링크

### 재현과 시험 계약

[개발용 스크립트](../../../scripts/experiments/finnhub_news_probe.py)와 [무통신 시험](../../../tests/experiments/test_finnhub_news_probe.py)을 추가했다. 정기 수집 worker·DB migration·송신 구현은 아니다.

```powershell
uv run python scripts/experiments/finnhub_news_probe.py --live --output tasks/verification/assets/news_samples/새_관측/metadata.json
uv run pytest tests/experiments/test_finnhub_news_probe.py -q
```

실제 조회는 본인 키로 API1회, 후보 원문 확인은 HEAD 최대12회/전체·최대4회/링크, 요청 timeout15초다. API 인증 헤더는 Finnhub 요청에만 붙이고 원매체/Google 요청에 전달하지 않는다. 원시 응답·기사 본문·이미지·원제·기사 URL을 파일에 남기지 않는다. 기존 출력 파일을 덮어쓰지 않는다.

| 검사 | 시험 기준·판정 |
| --- | --- |
| 미국 관련성 | 제목의 미국 시장/경제/정책 명시 또는 제한된 미국 기업 목록+사업 사건. 간접 국제뉴스·투자 의견·암호화폐 제외. 제목 규칙이므로 누락·오판 가능 |
| 중복 | ID·추적 인자 제거 URL·매체 접미사 제거 제목. 기발송 ID/URL 제외. 숫자·서로 다른 기업 사건을 임의로 합치지 않음 |
| 사건군 | 중간선거는 편성당1건으로 제한. 서로 다른 관점까지 동일 기사라고 단정하는 의미 중복 제거와 구별 |
| 날짜 | 미래/누락/오류·96h 초과 제외. 24h 우선 창과96h 보완은 실제 worker 편성 때 인수 필요 |
| Google News | 정상 HTTPS redirect만 추적. 원매체와 일치하는 CNBC/Reuters 호스트만 허용. 중간 페이지200·403·timeout·루프·임의 호스트는 미확인/제외 |
| 직접 링크 | 출처 일치 호스트의 HEAD2xx까지 시험 통과. HEAD403은 자동 확인 불가이며 URL 오류·유료벽의 확정 근거가 아님 |

이 시험은 제목 간 의미 유사도 모델·미국 상장기업 전체 목록·모든 매체를 지원하지 않는다. 같은 사건의 바꿔 쓴 제목을 모두 제거했다고 보고하지 않는다. 미확인 원문을 비공식 Google 복호화·내부 RPC·본문 파싱·차단 우회로 복구하지 않는다. 실제 제품에서 직접 링크에 HEAD 통과를 필수로 요구할지는 별도 인수 대상으로 남기며, 이 시험의 보수적0건을 API 뉴스 전체의 사용 불가로 확대하지 않는다.

### 실제 결과

| 항목 | 11/2 23:54:06 KST 실측 |
| --- | --- |
| 인증 응답 | HTTP200·100건·API1회 성공 |
| 앞선 표본과 관계 | SHA256 동일. 새로운100건이 추가됐다는 뜻이 아님 |
| 제목 관련성 | 후보5건 / 투자 의견·암호화폐11건 제외 / 명시적 미국 관련성 미충족84건 제외 |
| 중복 | 실제 후보 ID/URL/제목 중복0건. 중복 분기 동작은 합성 회귀로 검증 |
| 링크 확인 | HEAD9회. 후보 중 Google 경유4건 모두 중간 페이지200, CNBC 직접1건은403 |
| 보수적 링크 기준 통과 | 0건, 실제 편성/Telegram 전송 없음 |
| 개발용 관련 기사ID | 8711195, 8711197, 8710666, 8710980, 8709725 |

[집계](../assets/news_samples/finnhub_filter_followup/metadata.json) · [보존 범위](../assets/news_samples/finnhub_filter_followup/README.md). 제한 환경에서 최초 연결 실패 후 네트워크 권한으로 성공했다. Google은 정상 redirect1회 뒤 Google 중간 페이지에 머물렀으며 원매체 주소는 확보하지 못했다. 직접 CNBC 링크의403은 자동 HEAD 확인이 거절된 결과다. 브라우저의 본인 열람 가능 여부는 이 실험으로 확정하지 않았다.

**기술 판정:** 필터·중복·경유 실패의 제외 동작은 검증했다. 원매체 주소 복구 성공·아침08:00 실측·매일 뉴스3건 확보는 검증하지 못했다. 적격0건을 임의의 기사나 오래된 기사로 채우지 않는다. 링크 확인 실패는 뉴스가 없다는 상태와 구분한다.

### 이전 개인 전달·보관 조사 판정 · 11/3 후속 결정 전

11/2 [공식 약관](https://finnhub.io/terms-of-service)의 Intellectual Property와 Redistribution Rights and Personal Use를 재확인했다. 공개 근거로 확인한 것은 개인 비상업 이용, 제3자 공유 시 서면 승인, 이용 종료 시 해당 데이터 삭제, 원매체 권리 준수 책임이다. API 접근 성공·무료·개인 소량 호출이 원매체 이용권 전체를 취득했다는 뜻은 아니다.

본인 AWS/Neon→본인 Telegram, 메타90일/백업 보존, Telegram에 이미 전달한 메시지의 종료 시 삭제 처리는 공개 문서에 명확한 적용 설명이 없어 **미확인**으로 남는다. 별도 문의를 보냈거나 허가 회신을 받았다고 처리하지 않는다. 모든 개인 이용에 별도 서면 승인이 필수라는 조항을 발견한 것은 아니다. 공개 자료 조사 범위는 마쳤으나 구체적 적용 확인까지 완료됐다고 말할 근거는 없다.

[Telegram deleteMessage](https://core.telegram.org/bots/api#deletemessage)의 일반 Bot API 삭제 제한은 보통48시간이다. DB에서90일 뒤 삭제해도 Telegram의 장기 메시지는 자동으로 지워지지 않는다. 본인 클라이언트 수동 삭제·메시지 보존을 공급자가 어떻게 취급하는지도 위 문의에 포함했다. 회신 전에는 Finnhub 뉴스의 자동 전송/영속 뉴스 보관을 비활성으로 둔다.

**선정 결론:** Finnhub Free `general`을 개발용 조건부 채택해 기획서·기술 구성에 반영한다. 공식 발표는 직접 수집하고 Exa는 초기 필수 경로에서 제외한다. Finnhub 운영 채택은 원문 링크 확보·개인 전달/보관 적용 확인·08:00 관측 이후 결정한다. 현재 실측만으로 무조건 운영 채택을 권하지 않는다.

최종 검사와 실행 이력은 [11/3 결과](../../logs/2026-11-03_Finnhub_선정_검증.md)에 기록한다.
