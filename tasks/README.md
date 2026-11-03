# 작업 문서

현재 제품은 국내 ETF·개인 Telegram 자동 뉴스레터다. 이전 ETF/AM 승인/X 작업은 재사용·이행 이력이며 새 구현 순서는 [T WBS](../docs/planning/작업_분해_WBS.md)를 따른다.

제품 기준은 [docs](../docs/README.md), 시간·우선순위는 [WBS](../docs/planning/작업_분해_WBS.md)에서 관리한다.

## 현재 작업

| 작업 | 진입점 |
| --- | --- |
| T02 국내 시세·거래일·종목 DB | [작업](plans/국내_시세와_종목_DB.md) · [계약/시험](verification/market/국내_시세_어댑터와_종목_DB.md) · [결과](logs/2026-11-03_국내_시세와_종목_DB_구현.md) — 가격90일 확정·KIS/달력·활성10개/revision·0003·격리 PG 검증 |
| T01 KIS 인증 종가·이용 조건 | [실표본·T02 계약](verification/market/국내_ETF_API_표본_검증.md) · [11/3 결과](logs/2026-11-03_KIS_인증_종가와_이용_조건_인수.md) — 실전 인증·3종목×2일/휴장 응답·무통신 오류 통과, 본인 AWS/Telegram·가격90일 보관은 사용자 결정으로 허용·T01 완료 |
| 기획서 핵심화·WBS 날짜 재산정 | [기획서](../docs/프로젝트_기획서.md) · [시간/예정일 WBS](../docs/planning/작업_분해_WBS.md) · [11/3 결과](logs/2026-11-03_발표_기획과_Finnhub_관측_준비.md) — 평일5h·총95h 배정, 후속 기능/배포 포함11/29 완료 목표 |
| 발표 기획·링크·08시 검증 | [11/3 결과](logs/2026-11-03_발표_기획과_Finnhub_관측_준비.md) · [관측 계약](verification/news/Finnhub_시장뉴스_표본과_개인_전달.md) — 아침1회·오후 모두 기본꺼짐, 직접 주소3건 선정·11/4 08시 실관측 예약/미실행 |
| 현재 환경 변수·KIS 준비 | [11/3 정리 결과](logs/2026-11-03_환경_변수_정리.md) · [현재 설정 안내](../README.md#현재-환경-변수와-kis-준비) — 이전 변수 제거·KIS3개 추가, 인증 조회/제품 연동은 후속 |
| Finnhub 선정·필터·개인 전달 조건 | [실측·판정·한계](verification/news/Finnhub_시장뉴스_표본과_개인_전달.md) — 본인 개인용 채택, 100건→관련9건→직접 기사주소3건. 이메일 필수 아님·08시 실관측 예약 |
| 뉴스 링크·공식 발표·비공개 관리자 기획 | [기획서·Telegram 예시](../docs/프로젝트_기획서.md) · [HTML 시연](../docs/specifications/assets/관리자_와이어프레임.html) · [11/2 결정](discussions/2026-11-02_공식_발표와_비공개_관리자.md) · [비공개 배포](../docs/research/비공개_배포.md) |
| 개인 Telegram 권한 조사 | [공식 근거·판정·미발송 문의](../docs/research/데이터_이용_조건.md) · [11/2 결과](logs/2026-11-02_개인_Telegram_권한_조사.md) |
| 5주차 발표 초안 | [개인용 Telegram 뉴스레터 전환](presentations/5주차_개인용_뉴스레터_전환.md) — 11/1 기준, 발표 전 실제 개발 결과 갱신 |
| 개인용 뉴스레터 전환 | [작업](plans/개인용_뉴스레터_전환.md) · [확정 결정](discussions/2026-11-01_개인용_Telegram_뉴스레터_전환.md) · [API 표본](verification/market/국내_ETF_API_표본_검증.md) · [결과](logs/2026-11-01_개인용_뉴스레터_전환.md) |
| 11/1 4주차 발표 | [화면 자료](presentations/4주차_개발_계획_김유림.md) · [대본](presentations/4주차_발표_대본.md) · [준비 체크리스트](plans/11월_1일_발표와_서비스_준비.md) |
| 관리자 화면 정의 | [초기 3메뉴·상세 구성](../docs/specifications/관리자_화면_구조.md) · [인수 항목](verification/admin/관리자_화면과_승인_API.md) · [10/31 보완 결과](logs/2026-10-31_관리자_화면_정의_보완.md) |
| ETF·AM 승인 연결 | [M01/A01/A04 작업](plans/ETF_수집.md) · [통합 계약](verification/integration/ETF와_공통_뉴스_AM_연결.md) · [10/31 결과](logs/2026-10-31_ETF와_AM_승인_연결.md) |
| Exa·BLS 입력과 아침 편성 | [뉴스 수집 작업](plans/뉴스_수집.md) · [N01·N02 입력](verification/news/뉴스_공통_입력_계약.md) · [N08·N03·N09 어댑터/검사](verification/news/Exa와_BLS_어댑터_근거_검사.md) · [10/31 어댑터 구현 결과](logs/2026-10-31_Exa와_BLS_근거_검사_구현.md) · [실측 근거](verification/news/뉴스_API_재검토_표본과_예산.md) |
| 게시·운영 연결 | [X 게시](plans/X_게시.md) · [AWS](plans/클라우드_전환.md) |
| 문서·폴더 정리 | [작업 계획](plans/프로젝트_구조와_전체_일정_정리.md) · [10/30 결과](logs/2026-10-30_ETF_편성과_문서_정리.md) · [10/31 개발·발표 문서 보완](logs/2026-10-31_개발과_발표_문서_보완.md) |

## 폴더별 목록

- [plans: 현재 실행 계획](plans/README.md) · [완료·대체된 계획](plans/archive/README.md)
- [verification: 구현 계약·시험·관측 원본](verification/README.md)
- [logs: 실제 수행 기록](logs/README.md)
- [presentations: 주차별 발표·대본](presentations/README.md)
- [discussions: 질문·결정 과정](discussions/README.md)

과거 발표·논의·실측은 당시 사실로 보존하며 현재 요구사항을 덮어쓰지 않는다. 뉴스·지수 반복 관측은 [종료 기록](logs/2026-10-29_반복_관측_종료.md)을 따른다. 폴더 정리는 예약 재개·외부 게시 승인이 아니다.
