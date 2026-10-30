# 작업 문서

실행 계획·검증·수행 기록·발표·논의를 나눠 관리한다. 제품의 기준은 [docs](../docs/README.md)이며 폴더 역할은 [프로젝트 구조](../docs/프로젝트_구조.md)를 따른다.

## 현재 우선 작업

| 작업 | 기준·진입점 |
| --- | --- |
| **11/1까지 서비스 준비 · 최종 점검** | [실행 체크리스트](plans/11월_1일_발표와_서비스_준비.md) · [진행 기록](logs/2026-10-30_11월_1일_서비스_준비.md). **GitHub 읽기·Telegram 수신·X 키 로딩 확인, 개발 비용 계획 확정. 5분 리허설·수집 착수 자료 세부 확인 남음** |
| 11/1(일) · 4주차 발표 | [화면 자료](presentations/4주차_개발_계획.md) · [대본·예상 질문](presentations/4주차_발표_대본.md) · [결정 기록](discussions/2026-10-30_4주차_개발_계획_가독성_개선.md). 확정 기획 → 주차별 작업·완료 기준 → 진행 상황·시행착오 → 11/1까지 계정·API 준비 |
| 8주차 초까지 개발 | [범위·단계](../docs/planning/개발_범위와_단계.md) · [WBS](../docs/planning/작업_분해_WBS.md) · [우선순위](plans/개발_우선순위.md) |
| 공식 자료 수집 | [현재 조사](../docs/research/뉴스_수집.md) · [실행 계획](plans/뉴스_수집.md). Fed·BLS·BEA·SEC 10기업 고정. 초기 자료·기업 구성 확정, CIK·표본 검증·어댑터 구현 후속 |
| 관리자·API·데이터 | [제품 설계](../docs/specifications/README.md) · [관리자 검증](verification/admin/README.md) |
| 프로젝트 구조 정리 | [계획](plans/프로젝트_구조와_전체_일정_정리.md) · [결과](logs/2026-10-29_프로젝트_구조와_일정_정리.md) |

## 폴더별 목록

- [plans: 실행 계획](plans/README.md)
- [verification: 주제별 구현 계약·시험·관측](verification/README.md)
- [logs: 날짜별 실제 수행 기록](logs/README.md)
- [presentations: 주차별 발표·대본](presentations/README.md)
- [discussions: 질문·선택·결정 과정](discussions/README.md)

## 기록 원칙

`tasks 작업 내용` 요청에는 [tasks 스킬](../.agents/skills/tasks/SKILL.md)을 적용한다. 현재 범위/WBS를 다른 목록에 복제하지 않고 링크한다. 예전 발표·로그는 당시 사실이며 현재 요구사항을 덮어쓰지 않는다.

뉴스·지수 반복 관측은 [종료 기록](logs/2026-10-29_반복_관측_종료.md)을 따른다. 폴더 정리·일정 확장은 예약 재개나 외부 게시 승인이 아니다.

- [공식 자료 전환·개발 문서 재작성](plans/공식_자료_전환과_개발_문서_재작성.md) · [범위 확정 기록](discussions/2026-10-30_공식_자료와_세_지수_범위_확정.md)
