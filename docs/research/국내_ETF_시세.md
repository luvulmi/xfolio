# 국내 ETF 시세 · KIS 조건부 채택

- 갱신일: 2026-11-03. 가격은 KRW·KRX, 국내 상장 해외 ETF를 대상으로 한다.
- 11/3 사용자 확인: Open API 신청·발급정보 로컬 등록 완료. 공개 종목 마스터3건은 확인했으나 인증 시세 응답·이용 조건은 대기다.

## 공식 계약 조사

- [현재가 공식 예제](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_price/inquire_price.py): `/uapi/domestic-stock/v1/quotations/inquire-price`, TR `FHKST01010100`, 시장 `J`와 종목코드. 지속 실시간은 웹소켓을 안내하므로 REST를 스트리밍 시세로 표현하지 않는다.
- [일별 공식 예제](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py): `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, TR `FHKST03010100`, 일봉 `D`, 원주가 `1`. 한 요청 최대100건 설명이며 수정/원주가 기준을 섞지 않는다.
- [종목 마스터 공식 파서](https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/kis_kospi_code_mst.py): 공개 ZIP·CP949·후미228문자 분리 계약을 참조했다. 공식 예제의 TLS 검증 해제 코드는 재사용하지 않았다.
- [KIS 소개](https://apiportal.koreainvestment.com/intro)는 계좌 Appkey/App secret으로 토큰 발급을 안내한다. 11/1에는 약관 본문을 확보하지 못했으나 11/2에 [공식 고객 약관](https://file.koreainvestment.com/Storage/customer/guide/regards/openAPI_service_customer.html)을 직접 확인했다. 제5조③의 개인 업무 이용 허용·제3자 제공 금지를 확인했으며 본인 Telegram/AWS 경유의 명시 확인은 남아 있다. [현재 권한 조사](데이터_이용_조건.md)를 따른다. 계좌 보유만으로 이용/재전달 허가를 판단하지 않는다.

## 관리자에서 검색·확인·추가할 수 있는가 · 11/2 확인

**기술적으로 가능하며 본인 전용 프로그램 이용에는 약관상 근거가 있다.** 가격 조회 API 하나로 종목명을 검색하는 구조는 아니다. 공식 종목 마스터로 이름/코드를 찾고, 선택한 코드로 기본 정보·가격을 확인한 다음 앱의 관심 목록에 저장한다. 거래 주문이나 증권사 관심 그룹 변경과 무관하다.

1. 서버가 [공식 마스터](https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/kis_kospi_code_mst.py)의 단축코드·표준코드·한글명을 읽어 검색 목록을 만든다. TLS 검증은 유지한다. 이름 정규화와 부분 검색은 앱 기능이다.
2. 선택 코드를 [주식기본조회](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/search_stock_info/search_stock_info.py)로 확인한다. 공식 예제는 `/uapi/domestic-stock/v1/quotations/search-stock-info`, TR `CTPF1002R`, `PRDT_TYPE_CD=300`, `PDNO=종목코드`를 사용한다. 300에는 ETF 외 주식·ETN·ELW도 포함되므로 ETF 지원 여부 판정으로 대신할 수 없다.
3. 종목명·코드·KRX/KRW·ETF 유형·해외 기초자산 근거를 확인한다. 해외 ETF 분류를 마스터의 단일 플래그만으로 입증했다고 가정하지 않는다. 운용사 상품 정보 등 확인 근거와 확인일을 저장하고 미확인 종목은 등록 보류한다.
4. 필요할 때 서버에서 현재가를 조회해 기준시각과 함께 표시한다. 시세 장애는 종목 식별 실패와 구분한다. 초기 가격 검증이 안 된 종목을 정상 수집 가능으로 활성화하지 않는다.
5. 앱 DB에 저장하며 코드 중복과 활성 총10개 한도를 서버 트랜잭션으로 검사한다. 기본3종 외 추가는 최대7개다.

**정책 판단:** [고객 약관](https://file.koreainvestment.com/Storage/customer/guide/regards/openAPI_service_customer.html) 제5조③의 개인 업무 사용과 [제휴 안내](https://apiportal.koreainvestment.com/provider)의 개인 본인 이용 구분이 근거다. 본인 전용 관리 화면을 일반 고객 대상 시세 제공 서비스로 보지 않는다. 공개 마스터 접근/예제 코드 공개가 시세의 무제한 재배포 허가를 뜻하지는 않는다. AWS·Neon 보관/Telegram 경유의 적용 확인은 별도로 남는다.

**검증 범위:** 11/1 기본3종 이름·코드·ISIN 표본만 통과했다. 이번에는 공식 API 입력 계약을 확인했으며 인증 기본조회·현재가 응답이나 검색 UI는 실행하지 않았다. Open API 신청 후 세 ETF와 추가 후보 표본을 대조해야 한다.

## 인증과 운영 채택 조건

본인 계좌로 Open API를 신청하고 로컬 비밀 설정으로만 키를 관리한다. 계정/토큰을 Git이나 채팅으로 보내지 않는다. 공급자 제한·수신자1명 Telegram 전달·AI 입력 여부·보존 허용 범위를 별도 대조한다. Exa/원매체 권한도 유지 확인한다. 개인용이라는 이유로 자동 허용으로 처리하지 않는다.

인증 후 세 ETF의 최근 완료2거래일 종가와 장중 응답/실제 시각·한국 휴장일·분배락 표본을 확인한다. 장중 기준시각을 얻지 못하면 보완 API/제공처를 확인하고 현재가 발송을 활성화하지 않는다. 검증용 조회만 하며 주문 API는 호출하지 않는다.

월 50,000원 상한은 유지하되 이전 X 포함 견적은 새 서비스 견적이 아니다. KIS 신청 조건과 비용·호출 한도, Exa/AI/서버 비용을 확인한 뒤 [월 비용](월_비용.md)을 재산정한다.

[실제 표본과 계약](../../tasks/verification/market/국내_ETF_API_표본_검증.md) · [현재 운영 정책](../운영_정책.md)
