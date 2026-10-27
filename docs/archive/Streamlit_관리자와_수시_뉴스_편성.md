# Streamlit 관리자와 수시 뉴스 편성 이력

- 대체일: 2026-10-28, Asia/Seoul
- 현재 기준: [요구사항](../요구사항.md) · [기술 구성](../기술_구성.md) · [운영 정책](../운영_정책.md)

이전에는 Streamlit Community Cloud·Google 로그인·Neon 가상 초안을 관리자 목표로 두고 실제 비공개 로그인·저장·중복 방지를 시험했다. Cloud Run Jobs·Cloud Scheduler는 선택했으나 결제 미연결로 보류했고 GitHub Actions 간소화안도 검토했다.

추가 뉴스는 낮 동안 발견·검토되는 대로 하루 최대 2건을 게시하고 18:00부터 새 요청을 막는 구조였다. 승인 대기를 5분마다 확인하는 비용 가정도 사용했다. 10/28부터는 React/FastAPI·AWS와 **18:00 정기 발행**, 중요한 오류의 Telegram 알림으로 대체한다. 이전 3,242회 Cloud Run 비용을 새 AWS 견적으로 쓰지 않는다.

이전 시험 자체는 유효한 근거로 보존하며 새 구성의 구현 완료로 취급하지 않는다. [가상 클라우드 시험](../../tasks/logs/2026-10-25_클라우드_전환_준비.md) · [기존 배포 절차](../../deploy/cloud/README.md) · [3주차 발표](../../tasks/presentations/3주차_기술_조사.md) · [새 결정](../../tasks/discussions/2026-10-28_풀스택_MVP와_18시_뉴스_편성.md)
