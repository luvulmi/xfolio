# 조사·실험 스크립트

제품의 정기 worker가 아닌 제한 표본 조사 도구다. 실행 완료·공급자 채택 여부는 [작업 문서](../../tasks/README.md)와 [조사 기준](../../docs/README.md)의 근거를 확인한다. 아래 파일은 재현 경로와 시험 import를 유지하기 위해 이동하지 않는다.

| 주제 | 파일 |
| --- | --- |
| Marketaux | `marketaux_sample_probe.py`, `marketaux_incremental_probe.py`, `marketaux_focused_probe.py` |
| 다른 제공처·동일 사건 | `marketnewsapi_sample_probe.py`, `news_event_compare.py` |
| 공식 발표·사실 카드 | `official_macro_compare.py`, `bls_workflow_probe.py`, `sec_fact_card_preview.py` |
| AI 계약·요약·비교 | `openai_contract_probe.py`, `news_summary_probe.py`, `compare_openai_models.py` |
| 저장 실험 | `sqlite_probe.py` |
| 제공처 관측 | `provider_observation.py` |

인증된 외부 API 조회나 유료 모델 호출을 포함할 수 있다. 스크립트의 인자·한도·출력 경로를 확인한 뒤 해당 작업 범위에서 실행한다. `provider_observation.py`가 남아 있어도 종료한 반복 관측이 다시 활성화된 것은 아니다.

기능 검증은 [tests/](../../tests/README.md), 로컬 서버 도구는 [dev/](../dev/README.md)에 둔다. 비밀·실제 계정 설정을 실험 코드나 결과에 복사하지 않는다.
