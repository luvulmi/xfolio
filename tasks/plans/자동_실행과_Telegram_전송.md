# T06 자동 실행과 Telegram 전송

- 작성·갱신: 2026-11-04, Asia/Seoul
- 상태: 첫 구현·무통신/격리 DB 검증 완료, T06 전체는 진행 중
- 시작 관측: 2026-11-04 13:34:24 UTC
- 관련: [공통 계약](../verification/integration/병렬_개발_공통_계약.md) · [T04 검사](../verification/integration/아침_뉴스레터_편성과_발송_검사.md)

## 목표와 범위

T04 편성·검사를 재사용하는 독립 worker 진입점, 한국 거래일07:50 준비/08:00 전송 스케줄, 영속 Telegram outbox와 모의 송신을 구현한다. 기본은 무통신 모의 모드다. 실제 Telegram·유료 제공처·AWS·운영 DB 실행은 이번 범위가 아니다.

## 작업

- [x] T04와 병렬 공통 계약 확인
- [x] Telegram plain text 분할·429·결과 불명·모의 adapter
- [x] 0007 outbox·원자 점유·중복/재시작·본문 없는1년 메타데이터
- [x] 현재 설정·종목·개장일·예산 원장 조회와 직전 검사
- [x] 기본 모의 worker·07:50/08:00 스케줄·휴장 수집 전 차단
- [x] 무통신23건·격리 DB17건 검증과 [실제 결과](../logs/2026-11-04_자동_실행과_Telegram_전송.md) 기록
- [ ] T02/T03 실제 수집·유료 요약 adapter와 설정 freeze 연결
- [ ] T07 실제 한국 거래일 아침 수신·재시작 운영 인수

## 경계

설정 쓰기는 T05의 `NotificationSettingsStore`만 담당한다. worker는 같은 서비스로 읽는다. 공통 의존성·migration metadata·목차·WBS는 통합 담당이 반영한다. 실제 아침 수신·외부 제공처 정시 수집은 T07 인수로 남긴다.

`--live --schedule`과 `--live --phase prepare`는 실제 수집 adapter 미인수로 차단한다. 현재 진입점의 기본 `--once`·`--schedule`은 합성 무통신 모의다. [구현 계약](../verification/integration/자동_실행과_Telegram_전송.md)에 실행 환경·안전 경계·보존을 기록했다.
