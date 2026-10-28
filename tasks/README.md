# 작업 문서

작업 계획·구현 계약·검증 근거·수행 기록·발표·논의를 구분한다. 프로젝트 기준과 선택 근거는 [프로젝트 문서](../docs/README.md)에 둔다.

문서 파일명은 한글, 폴더명은 영어 `snake_case`를 사용한다. 그림·관측 자료는 해당 폴더의 `assets/`에 둔다.

## 작업 요청 방법

`tasks 뉴스 수집을 구현하자` 또는 `$tasks 지수 종가의 누락 처리를 검증하자`처럼 요청하면 [tasks 스킬](../.agents/skills/tasks/SKILL.md)이 기존 문서를 확인해 알맞은 폴더에 작업 문서를 작성·갱신하고 실제 작업·검증·결과 기록까지 진행한다. 계획만 필요하면 `tasks 뉴스 수집 구현 계획만 작성해줘`처럼 범위를 지정한다.

## 현재 작업

| 작업 | 계획·검증 |
| --- | --- |
| 풀스택 2주 MVP | [우선순위](plans/개발_우선순위.md) · [2화면·8API·8저장·18시·Telegram 계약](verification/2주_MVP_구현_계약.md) |
| 기획 상세 확정 | [뉴스 선정 고정 사례](verification/뉴스_선정_고정_사례.md) · [관리자 화면·승인 API](verification/관리자_화면과_승인_API.md) · [상세화 결과](logs/2026-10-28_뉴스_선정과_승인_기획_상세화.md) |
| 뉴스 선정·관리자 초기 구현 | [구현·검증 결과](logs/2026-10-28_뉴스_선정과_관리자_초기_구현.md) · [OpenAPI](../contracts/openapi.json) |
| AWS 배포 전환 | [단일 VM/Compose 계획](plans/클라우드_전환.md) · [이전 가상 클라우드 시험](logs/2026-10-25_클라우드_전환_준비.md) |
| 지수 수집 | [계획](plans/지수_수집.md) · [종가 조회 검증](verification/지수_종가_조회.md) |
| 여러 거래일의 오전 도착 | [검증 계획·관측 기록](verification/지수_오전_도착.md), 현재1/5 |
| 뉴스 수집·아침 미리보기 | [현재 두 지수 관련 Marketaux 단일 흐름](discussions/2026-10-25_두_지수_뉴스_단일_흐름.md) · [계획](plans/뉴스_수집.md) · [새 질의·간격·비용 시험](verification/두_지수_뉴스_질의와_감시_비용.md) · [구현/예시](verification/뉴스_수집과_아침_미리보기.md) |
| X 게시 | [계획](plans/X_게시.md) |
| 기술 조사 | [3주차 조사 계획](plans/3주차_조사_계획.md) · [후속 검증](verification/기술_조사_후속_검증.md) |
| 개발 일정 | [최신 기획과 선행 구현을 반영한 주차별 일정·30시간 배분](plans/개발_일정.md) |
| OpenAI 분석·모델/근거/비용 비교 | [계획](plans/OpenAI_분석과_비용_비교.md) · [실측·판정](verification/OpenAI_분석과_제공처_비교.md) |

10/28 목표는 React·TypeScript·FastAPI·PostgreSQL·Docker/AWS, 아침과 **18시 최대 2뉴스**, 중요 장애의 **Telegram**이다. 기존 Python 수집·가상 미리보기·Neon/Streamlit 인증에 이어 뉴스 선정 정책·React/API·migration 초기 코드를 작성했다. 실제 Google/PostgreSQL·실기사 승인 통합과 X·worker·Telegram·AWS는 후속이다. [결정](discussions/2026-10-28_풀스택_MVP와_18시_뉴스_편성.md) · [초기 구현 결과](logs/2026-10-28_뉴스_선정과_관리자_초기_구현.md)

## 발표 자료

- [1주차 개발 환경](presentations/1주차_개발_환경.md)
- [2주차 요구사항](presentations/2주차_요구사항.md) · [발표 대본](presentations/2주차_발표_대본.md)
- [3주차 화면용 시각 요약·전체 기술 스택 Mermaid·Luna 월 비용](presentations/3주차_기술_조사.md) · [발표 대본·예상 질문](presentations/3주차_발표_대본.md)
- [4주차 풀스택 스택·18시 뉴스·Telegram·2주 MVP](presentations/4주차_개발_계획.md) · [발표 대본·예상 질문](presentations/4주차_발표_대본.md)

## 기록과 논의

- [날짜별 작업 기록](logs/README.md)
- [풀스택 MVP·18시 뉴스·Telegram 확정](discussions/2026-10-28_풀스택_MVP와_18시_뉴스_편성.md)
- [새 기획과 30시간 범위 반영](logs/2026-10-28_풀스택_MVP_기획_확정.md)
- [4주차 발표 재구성·개발 우선순위 작성](logs/2026-10-28_4주차_발표와_개발_우선순위.md)
- [관찰 기업·MarketNewsAPI 실기사·클라우드 비용](logs/2026-10-25_관찰_기업_실기사_클라우드_비용.md)
- [SEC 공시·OpenAI 초안·발표 마무리](logs/2026-10-25_SEC_공시_요약_발표_마무리.md)
- [Luna 모델 확정·3주차 발표 정리](logs/2026-10-25_Luna_모델_확정과_3주차_발표_정리.md)
- [발표용 뉴스 제공처·범위·예산 가안](logs/2026-10-25_발표용_제공처_예산_가안.md)
- [OpenAI 공통 가상 분석·모델/공식 자료/비용 비교](logs/2026-10-25_OpenAI_분석_비용_비교.md)
- [뉴스 구현 결정·동일 사건 비교·3주차 발표 갱신](logs/2026-10-25_뉴스_기술_결정과_발표_갱신.md)
- [지수 조회 구현·시험](logs/2026-10-24_지수_조회.md)
- [Marketaux 실제 조회·증분/한도·OpenAI 요약 실측](logs/2026-10-24_뉴스_샘플_검토.md)
- [좁힌 뉴스·가상 미리보기 구현과 로컬 배포](logs/2026-10-24_뉴스_미리보기_구현.md)
- [문서 구조 정리](logs/2026-10-24_문서_정리.md)
- [tasks 스킬 추가](logs/2026-10-24_tasks_스킬_추가.md)
- [논의와 결정 과정](discussions/README.md)
- [3주차 발표·추가 뉴스 2건·아침 축소 검토](discussions/2026-10-24_3주차_발표와_게시_편성.md)
- [리더 제공 OpenAI 가이드·현재 사용·개선 추천](discussions/2026-10-24_OpenAI_가이드_적용_검토.md)
- [발표 갱신 위치·뉴스 기술 결정 보완안](discussions/2026-10-25_발표_보완과_뉴스_기술_결정.md)
- [DB·관리자·수집·예약의 무료 클라우드 전환 조사](discussions/2026-10-25_무료_클라우드_전환.md)
- [월 5만 원·Marketaux 단일 뉴스 범위](discussions/2026-10-25_예산과_Marketaux_뉴스_범위.md)
- [두 지수 관련 뉴스 단일 흐름](discussions/2026-10-25_두_지수_뉴스_단일_흐름.md)
- [두 지수 뉴스 질의·감시 비용 재검토](logs/2026-10-25_두_지수_뉴스_질의_감시_비용.md)

작업 계획은 plans/, 시험 방법·결과·근거는 verification/, 날짜별 수행 결과는 logs/, 주차별 발표·대본·이미지는 presentations/, 질문·답변은 discussions/에 둔다. 같은 사실을 복사해서 중복 관리하지 않는다.
