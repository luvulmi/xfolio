# 검증 원본과 그림

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
