# yfinance 지수 수집 채택

- 결정일: 2026-10-23, Asia/Seoul
- 상태: 사용자 확정, 문서 반영 완료. 라이브러리 설치·수집 구현·실제 응답 시험 전
- 결정 기록: [상세 기획 세션 C03](../../../tasks/brain_storm/session_2026-10-21_pre_research_planning.md)
- 관련: [지수 수집·게시 모드](../../market_search_and_publishing_modes.md) · [기술 스택](../../project_structure_and_tech_stack.md)

## 확정한 선택

Market Pipeline의 지수 수집 수단은 **yfinance**로 정한다. Yahoo Finance 데이터를 가져오는 Python 라이브러리이며 Yahoo의 공식 SDK는 아니다. 무료 라이브러리로 개인 학습·개발을 간단하게 시작하려는 사용자 선택이다. 일반 가격 조회용 API 키 발급을 시작 조건으로 두지 않는다. [프로젝트 안내](https://github.com/ranaroussi/yfinance)

| 대상 | Yahoo 심볼 | 수집·계산 |
| --- | --- | --- |
| S&P 500 | `^GSPC` | 최근 완료 미국 거래일 종가와 그 직전 거래일 종가 |
| Nasdaq-100 | `^NDX` | 같은 기준의 종가. Nasdaq Composite인 `^IXIC`와 구분 |

기존 검색·원문 추출 우선안과 FRED 우선 후보는 비교 이력으로 둔다. 검색이나 다른 제공처로의 자동 대체는 이번 결정에 포함하지 않는다. 뉴스 제공처 1곳과 개발·테스트 승인 → 안정화 후 자동 게시 방침은 유지한다.

## 구현 기준

`아침 예약 실행 → yfinance로 두 지수의 일별 종가 조회 → 완료 거래일 확인 → 등락률 코드 계산 → 검증 → 게시 초안`

1. 일별 가격은 `interval="1d"`, `auto_adjust=False`를 명시하고 `Close`를 사용한다. 조정 종가를 원 지수 종가와 섞지 않는다. [download 공식 문서](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
2. 미국 시장의 최근 완료 거래일과 직전 거래일에 해당하는 유효 종가를 고른다. 마지막 행이라는 이유만으로 사용하지 않고 휴장·서머타임·미완료 거래일을 확인한다.
3. 등락률은 `(종가 / 직전 거래일 종가 - 1) × 100`으로 계산한다. 원값 정밀도를 보존하고 기존 R08의 표시·반올림 기준을 적용한다.
4. `index_id`, `symbol`, `trade_date`, `close`, `previous_trade_date`, `previous_close`, `change_pct`, `provider`, `source_url`, `retrieved_at`을 공통 출력에 남긴다. 출처는 Yahoo Finance, 수집 수단은 yfinance로 구분한다. 제공되지 않는 갱신 시각·확정 플래그는 만들어 넣지 않는다.
5. 빈 응답·NaN·잘못된 날짜·가격·호출 제한·통신 오류가 있으면 기존 오류 처리를 적용한다. 이전 날짜 값을 새 종가로 복사하거나 AI 추정으로 보완하지 않는다. 두 지수의 필수 자료를 검증하지 못하면 아침 호를 보류한다.

일반 조회료와 라이브러리 사용료는 계획상 0원으로 두고, 지수용 유료 웹 검색 호출료는 현재 기본 구성에 합산하지 않는다. 기존 X·AI 등의 약 21,387원 부분 견적과 총 30,000원 상한은 유지한다. 실제 공개 데이터 이용 비용까지 0원이라고 확정한 것은 아니다.

## 남은 검증

- 개발 시 `pyproject.toml`·`uv.lock`에 의존성을 반영하고 README에 설치·실행 방법을 적는다. 이번 요청은 문서 갱신이며 설치나 코드 구현은 수행하지 않았다.
- 두 심볼의 실제 응답, 날짜·종가·결측 처리, 등락률 계산과 오전 목표 시각의 자료 도착을 시험한다. 외부 API 없이 재현할 수 있는 기능 검증도 구현과 함께 추가한다.
- yfinance 코드의 Apache 2.0 라이선스와 Yahoo 데이터 이용 조건을 구분한다. 비영리 목적의 개발 채택은 확정했지만 정기 X 공개 게시 허가 취득을 뜻하지 않는다. 공개 전환 전에 해당 용도의 이용 범위를 확인한다. [라이선스](https://github.com/ranaroussi/yfinance/blob/main/LICENSE.txt)
