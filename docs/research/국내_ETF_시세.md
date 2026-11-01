# 국내 ETF 시세 · KIS 조건부 채택

- 확인일: 2026-11-01. 가격은 KRW·KRX, 국내 상장 해외 ETF를 대상으로 한다.
- 계좌 있음·Open API 신청 필요. 공개 종목 마스터3건은 확인했으나 인증 시세 응답·이용 조건은 대기다.

## 공식 계약 조사

- [현재가 공식 예제](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_price/inquire_price.py): `/uapi/domestic-stock/v1/quotations/inquire-price`, TR `FHKST01010100`, 시장 `J`와 종목코드. 지속 실시간은 웹소켓을 안내하므로 REST를 스트리밍 시세로 표현하지 않는다.
- [일별 공식 예제](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py): `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, TR `FHKST03010100`, 일봉 `D`, 원주가 `1`. 한 요청 최대100건 설명이며 수정/원주가 기준을 섞지 않는다.
- [종목 마스터 공식 파서](https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/kis_kospi_code_mst.py): 공개 ZIP·CP949·후미228문자 분리 계약을 참조했다. 공식 예제의 TLS 검증 해제 코드는 재사용하지 않았다.
- [KIS 소개](https://apiportal.koreainvestment.com/intro)는 계좌 Appkey/App secret으로 토큰 발급을 안내한다. [이용안내](https://apiportal.koreainvestment.com/about-howto)에서 이번 비로그인 조회로 약관 본문을 확보하지 못했다. 계좌 보유가 API 이용/재전달 허가의 증거는 아니다.

## 채택 조건

본인 계좌로 Open API를 신청하고 로컬 비밀 설정으로만 키를 관리한다. 계정/토큰을 Git이나 채팅으로 보내지 않는다. 공급자 제한·수신자1명 Telegram 전달·AI 입력 여부·보존 허용 범위를 별도 대조한다. Exa/원매체 권한도 유지 확인한다. 개인용이라는 이유로 자동 허용으로 처리하지 않는다.

인증 후 세 ETF의 최근 완료2거래일 종가와 장중 응답/실제 시각·한국 휴장일·분배락 표본을 확인한다. 장중 기준시각을 얻지 못하면 보완 API/제공처를 확인하고 현재가 발송을 활성화하지 않는다. 검증용 조회만 하며 주문 API는 호출하지 않는다.

월 50,000원 상한은 유지하되 이전 X 포함 견적은 새 서비스 견적이 아니다. KIS 신청 조건과 비용·호출 한도, Exa/AI/서버 비용을 확인한 뒤 [월 비용](월_비용.md)을 재산정한다.

[실제 표본과 계약](../../tasks/verification/market/국내_ETF_API_표본_검증.md) · [현재 운영 정책](../운영_정책.md)
