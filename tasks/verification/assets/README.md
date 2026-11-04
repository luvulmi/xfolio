# 검증 원본과 그림

- [T03 무료 수집·공식 발표 파싱](news_samples/t03_2026-11-04/README.md) — 11/4 무료4출처 수동 조회·공식4표본 해시/집계. 유료 AI·제품 정시·Telegram 송신 없음

- [T02 공개 종목 마스터 실측 요약](market/KIS_종목_마스터_2026-11-03/표본_요약.json) — 2,580행 중 지원6자리1,772행·기본3개, 시세 재조회 아님

- [KIS 인증 종가·주말 휴장 실표본](market/kis_close_2026-11-03T225345459055KST/README.md) · [11/3 공식 근거/해시](market/KIS_인수_공식근거_2026-11-03/README.md) — 실전5회·3종목×2일, 키/토큰/계좌정보 제거·사용자 개인 이용 허용 결정으로 T01 완료

- [Finnhub 시장뉴스 집계 표본](news_samples/finnhub_2026-11-02T144130Z/README.md) — 11/2 인증1회100건, 원문/키 미보관·지연/08시/원매체 링크 검증과 구분
- [Finnhub 필터·경유 후속](news_samples/finnhub_filter_followup/README.md) — 23:54 재조회100건, 제목 후보5건·HEAD9회·원매체 확인 통과0건. 원제/URL/본문 미보관
- [Finnhub 직접 링크 보완](news_samples/finnhub_links_2026-11-03/README.md) — 11/3 22:00 실제100건→후보9건→직접 기사주소3건, 원문 열람 검증과 구분

- [KIS 개인고객 약관·확보 정보](market/개인_Telegram_이용_정책_2026-11-02/README.md) — 11/2 권한 조사 원본, 로그인·계좌정보 없음

- [KIS 공개 종목 식별 표본](market/kis_2026-11-01/selected_master.json) — 가격/계좌 정보 없음

실제 관측 자료와 시험 산출물을 보존한다. 현재 운영 데이터나 API 입력 fixture로 자동 사용하지 않는다. 생성 시각·시험 계약을 함께 확인한다. 뉴스/지수 반복 관측은 종료 상태이며 파일 정리는 관측 재개가 아니다.

| 폴더 | 내용 |
| --- | --- |
| market/ | 지수 종가 조회·실행 메타데이터 |
| news_samples/ | 뉴스 제공처·AI 제한 표본 |
| news_cases/ | 동일 사건 대조·SEC 사실 카드 |
| provider_observations/ | 종료된 뉴스 반복 관측 |
| ai_compare/ | 모델·공식 근거 비교 |
| workflow/, news_workflow/ | 각 시점의 실자료 연결 시험 |
| auth/ | 로그인 검증 |
| cloud/ | 이전 Streamlit/Neon 시험 |
| preview/ | 미리보기 그림 |
| integration/ | ETF·AM 4글의 격리 HTTPS/API/DB 시험 화면. 실제 시장 수치·X 성공이 아님 |
