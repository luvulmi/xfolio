# ETF 가격 데이터 수집 · yfinance

- 갱신: 2026-10-30, Asia/Seoul. 사용자 선택으로 지수 자체에서 **SPY·QQQ·DIA ETF**로 전환한다.
- 상태: 기술 선택·구현 목표. 현재 코드는 `^GSPC`·`^NDX` 두 지수이며 ETF 전환은 미구현이다.
- 기준: [요구사항](../요구사항.md) · [가격·거래일 정책](../운영_정책.md#r08-etf-가격반올림수정치) · [작업](../../tasks/plans/ETF_수집.md)

| ETF 심볼 | 추종 대상 | 게시할 값 |
| --- | --- | --- |
| SPY | S&P 500 | ETF 1주 시장 종가(USD)·직전 거래일 대비 가격 등락률 |
| QQQ | Nasdaq-100 | 같은 기준. Nasdaq Composite와 구분 |
| DIA | Dow Jones Industrial Average | 같은 기준 |

ETF는 지수 자체가 아니다. 지수 포인트·배당 재투자 총수익률로 표현하지 않는다. 출처는 Yahoo Finance, 수집 라이브러리는 yfinance로 표시한다. 일반 조회용 API 키는 필요하지 않지만 Yahoo 공식 SDK는 아니다.

## 구현 전에 고정할 계약

1. `interval="1d"`, `auto_adjust=False`의 `Close`를 사용한다. 최근 완료 미국 거래일과 직전 거래일을 거래소 달력으로 고르고 휴장·서머타임·미완료 일봉을 제외한다.
2. `(close / previous_close - 1) × 100`으로 가격 등락률을 계산한다. 세 ETF의 거래일·통화·가격 기준이 일치해야 하며 하나라도 누락되면 AM을 보류한다.
3. ETF명·심볼·USD·거래일·원본 Close·직전 Close·계산값·출처 URL·조회 시각·가격 기준을 보존한다. 기존 `IndexClose`/`MarketSnapshot`의 이름·필드·UI와 호환성을 M01에서 정하고 ETF를 지수로 오표기하지 않는다.
4. 배당락은 분배금을 포함하지 않은 가격 변화임을 유지한다. 분할·수정치로 두 날짜의 비교 기준이 달라지면 확인 전 보류한다. `Adj Close`와 `Close`를 섞거나 AI로 결측을 보완하지 않는다.
5. 종가·등락률은 십진 HALF_UP 소수 둘째 자리, 음의 0은 0.00으로 표시한다. 세 ETF를 하나의 X 글에 넣고 가중 길이·출처 표기를 검사한다.

## 근거와 이용 조건

[yfinance 안내](https://github.com/ranaroussi/yfinance) · [download 문서](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) · [코드 라이선스](https://github.com/ranaroussi/yfinance/blob/main/LICENSE.txt)

라이브러리의 Apache 2.0과 데이터 이용 권한은 별개다. ETF를 택해도 정기 X 게시·외부 AI·차트 공개 권한이 자동 부여되지 않는다. 첨부 AI 답변의 ‘가공하면 안전’, ‘출처만 쓰면 가능’은 확인된 계약 근거로 사용하지 않는다. [이용 조건](데이터_이용_조건.md)

기존 두 지수의 [구현 계약](../../tasks/verification/market/지수_종가_조회.md)·[실제 조회](../../tasks/logs/2026-10-24_지수_조회.md)·[오전 관측](../../tasks/verification/market/지수_오전_도착.md)은 당시 근거로 보존한다. 종료한 관측은 재개하지 않는다. FRED·FMP 등 이전 비교는 [지수 API 이력](../archive/지수_API_검토_이력.md), 현재 비용은 [월 비용](월_비용.md)을 따른다.
