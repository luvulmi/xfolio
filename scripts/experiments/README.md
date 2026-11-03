# 조사·실험 스크립트

- `kis_market_probe.py`: 기본 실행은 기존 공개 마스터3종목 검증(인증 없음). `--mode check-config`는 루트 `.env`3개 존재/실전모의 주소 일치를 무통신 확인, `--mode close --environment real`은 인증1·휴장일1·일봉3회로 완료2일 원종가를 검증한다. 토큰은 메모리, 허용 필드만 `tasks/verification/assets/market/kis_close_<KST_시각>/close_probe.json`에 보존한다. TLS 유지·20초 timeout·직렬1.1초·재시도0회·계좌/주문 없음. 재실행마다 인증하므로 반복 운영용 아님, 휴장일은 공식 권장1일1회. [실측·오류/부분 성공·T02 인계](../../tasks/verification/market/국내_ETF_API_표본_검증.md).
- `finnhub_news_probe.py`: 미국 관련 제목·중복·원문 주소 검증. `uv run python scripts/experiments/finnhub_news_probe.py --live --output tasks/verification/assets/news_samples/새_관측/metadata.json`. `.env`의 `FINNHUB_API_KEY`로 API1회·Google 정상 HEAD 최대12회. 공급자가 제공한 직접 개별 기사주소는 HEAD 성공 없이 인정하고 열람 가능 여부는 미검증으로 표시한다. 원시 응답/기사 본문/제목/URL/키 저장·Telegram 송신 없음. CNBC/Reuters만 지원하는 개발 시험이며 운영 어댑터가 아니다. [검증·한계](../../tasks/verification/news/Finnhub_시장뉴스_표본과_개인_전달.md).
- `finnhub_slot_probe.py`: 평일08:00 KST 1회 관측. `uv run python scripts/experiments/finnhub_slot_probe.py --slot 2026-11-04T08:00:00+09:00 --output tasks/verification/assets/news_samples/finnhub_slot_2026-11-04_0800/metadata.json`은 무통신 계획만 출력한다. 예약 시에만 `--live`를 붙인다. 슬롯 전 최대90초 대기, 실제 API 요청 시작08:00:00~08:00:59만 정시 인정, 지각은 무통신 누락 기록. 결과/claim 존재 시 재조회하지 않는다. 요청·수신·발행시각을 구분하고 원문 열람/Telegram 수신 성공으로 확대하지 않는다.

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
