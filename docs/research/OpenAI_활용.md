# R4 · OpenAI 활용과 모델 비교

- 갱신일: 2026-10-25, Asia/Seoul. 기존 Mini 8건에 동일 가상6건의 Mini/Luna 비교와 공식 BLS 직접/Web search 시험을 추가했다.
- 범위: 공식 문서·로컬 계약 시험·직접 작성한 가상 자료의 실제 생성·usage·지연 확인. 실뉴스 품질·운영자 검토는 미확인
- 기준: [조사계획](../../tasks/plans/archive/3주차_조사_계획.md)
- 현재 선택: **`gpt-6-luna`를 생성·분석의 기본 모델로 확정**했다. Mini 실제 생성8건과 Luna 동일 가상6건 시험은 이력으로 보존한다. Luna의 SEC 실적 공시 품질과 계정의 현재 잔액 숫자는 아직 확인하지 않았다. 이전 잔액 부족 실패는 [시험 이력](../../tasks/verification/news/뉴스_샘플과_요약_시험.md#등록-키로-실제-인증한-결과)과 구분한다.

## 결론

**`gpt-6-luna` + 공식 Python SDK의 Responses API + Pydantic 구조화 출력**을 생성·분석 기술로 확정한다. 별도 에이전트 프레임워크·자율 웹 탐색·벡터 DB를 첫 버전의 필수 요소로 추가하지 않는다. 모델 확정은 운영 품질 시험 완료를 뜻하지 않으며 실패·근거 부족은 게시 보류다. SDK 사용법은 [공식 SDK 안내](https://developers.openai.com/api/docs/libraries)에서 확인했다.

## 모델 후보와 가격

표는 일반 텍스트 100만 토큰당 USD 입력/출력 단가다. 캐시·Batch·특수 처리 할인은 계산하지 않았다. 계정 접근과 호출 한도는 실제 프로젝트에서 별도 확인해야 한다.

| 후보 | 입력 | 출력 | 조사 판단 |
| --- | --- | --- | --- |
| GPT-5.4 Mini | $0.75 | $4.50 | 이전 개발·SEC 사실 카드 시험 모델. 비교 이력으로 보존 |
| **GPT-6 Luna** | **$0.10** | **$0.50** | **현재 확정 모델**. 동일 가상6건 6/6 기계 검사 통과; SEC 실공시 문안 검증 후 게시 연결 |
| GPT-5.6 Terra | $2.00 | $12.00 | 비교 후보. 비용과 품질 향상의 실익을 같은 샘플로 평가 |
| GPT-5.4 nano | $0.20 | $1.25 | 저가 비교 자료로 기록. 공식 페이지 Deprecated 표시로 신규 채택 보류 |

근거: [Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano). GPT-5 Mini도 [모델 페이지](https://developers.openai.com/api/docs/models/gpt-5-mini)에 Deprecated 표시가 있어 저렴하다는 이유만으로 선택하지 않는다. 최신 전체 가이드는 [Using GPT-6](https://developers.openai.com/api/docs/guides/latest-model)로 연결되지만, 최신 모델 전체를 반드시 채택해야 한다는 의미는 아니다. 모델 종료 일정은 구현 시작 때 재확인한다.

### 현재 코드·추가 실측

공통 `src/xfolio/analysis.py`가 가상 자료의 Structured Outputs·근거 검사·usage/캐시 비용 추정을 맡고, `xfolio ai-preview`가 이 결과를 기존 가상 아침 미리보기에 연결한다. 실제 기사 입력은 연결하지 않았다. 같은 프롬프트의 Mini/Luna 6건은 각각 4선정·2보류 및 기계 검사 6/6을 통과했고 실측 비용은 $0.0051210/$0.0005432였다. Luna 가상 아침 1건 연결도 2글 `dry_run`에 성공했다. 영문 기관명과 금액 단위 표현은 사람이 문안을 다듬어야 한다. [상세 결과](../../tasks/verification/ai/OpenAI_분석과_제공처_비교.md)

공식 BLS 발표 직접 조회는 OpenAI 비용 없이 성공했고, `bls.gov`로 제한한 Web search는 1도구 호출·8,598입력/157출력 토큰으로 같은 수치와 원문 링크를 반환했다. 검색 1회 비용 추정은 캐시 쓰기까지 포함해 $0.011048125였다. 이 실측은 이전 검토 결과다. 2026-10-30 확정한 제품 범위는 Fed·BLS·BEA 공식 발표와 SEC 공시이며, 실제 어댑터와 허용 근거를 연결해야 한다. Web search를 전수 뉴스 수집으로 채택하지 않는다. [이전 월 시나리오](../archive/월_비용_산정_이력.md#이전-편성의-절감-검토-관측과-조건부-시나리오)

## 기능별 적용

| 단계 | AI 작업 | Python·운영자 작업 |
| --- | --- | --- |
| 수집 후 필터 | 기사 분류·관련성·사건 중요성 설명·근거 추출 | 관찰 기업·시각·기사 ID·중복의 확실한 조건을 먼저 필터 |
| 후보 생성 | 선택 자료를 한국어 요약·명사형 X 초안으로 작성 | 지수 등락률 계산, 값·단위·기간·URL 연결 |
| 검증 | 게시문과 근거의 모순·근거 누락 표시 | 원본 숫자·날짜·길이·중복·마감·승인·한도 검사 |
| 게시 결정 | 매매 지시나 근거 없는 전망을 생성하지 않도록 지침 적용 | 운영자가 원문·초안 검토 후 승인 |

AI 검증 실패 시 기존 정책대로 1회 재생성·재검증 후 보류한다. 같은 모델의 재검사는 독립적인 사실 보증이 아니며 개발·테스트에는 운영자 확인을 적용하고 안정화 후에는 운영 정책의 자동 검증·게시 조건을 적용한다. 기사 본문은 지시가 아닌 분석 대상으로 전달하고, 기사 안의 명령을 도구 실행·게시 승인으로 해석하지 않도록 한다.

## 구조화 출력 예시

[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)는 Pydantic 모델과 `responses.parse`를 지원한다. 결과 형식 준수와 사실 정확성은 별개다. 거절·불완전 응답·파싱 실패도 보류 대상으로 처리해야 한다.

아래는 API를 실행하지 않은 적용 예시다. 기존 `openai`·`pydantic` 의존성을 사용한다.

```python
from openai import OpenAI
from pydantic import BaseModel


class Claim(BaseModel):
    text_ko: str
    source_id: str
    evidence: str


class NewsDraft(BaseModel):
    category: str
    selected: bool
    selection_reason: str
    claims: list[Claim]


client = OpenAI(max_retries=0)  # 재시도는 애플리케이션의 누적 한도로 관리
response = client.responses.parse(
    model="gpt-6-luna",
    input=[
        {
            "role": "system",
            "content": "제공 자료만 사용해 한국어로 작성. 근거가 없으면 제외.",
        },
        {"role": "user", "content": "검증 가능한 기사 ID·시각·허용 본문/요약"},
    ],
    text_format=NewsDraft,
    max_output_tokens=2000,
    store=False,
)
draft = response.output_parsed
```

가상 입력은 `sample_01 / A기업 3분기 매출 100억 달러, 전년 동기 90억 달러`처럼 출처에 이미 있는 값으로 구성한다. 기대 출력은 `A기업 3분기 매출 100억 달러`와 해당 근거·선정 이유다. 실제 기사를 조회하거나 모델이 생성한 결과가 아니다. 구성기업 여부를 확인하기 전 이 가상 기업을 발행 후보로 승인하지 않는다.

## 비용·보관과 다음 확인

Responses API 자체 별도 사용료 대신 모델 토큰 요금이 적용되며 웹 검색 같은 도구는 별도 과금된다. 초기 구성은 제공처가 준 자료만 모델에 입력하고 내장 검색은 사용하지 않는 것으로 견적한다. [가격표](https://developers.openai.com/api/docs/pricing)

추론 토큰도 출력 요금에 포함되므로 눈에 보이는 요약 길이만으로 비용을 계산하지 않는다. 실행 시 API의 usage와 출력 한도를 기록한다. [추론 안내](https://developers.openai.com/api/docs/guides/reasoning)

`store=False`를 요청하더라도 모든 서버 기록이 즉시 사라진다고 보지 않는다. 기본 Responses 저장과 abuse monitoring, 조직별 데이터 통제를 확인하고 기사 제공처의 외부 AI 전송·보관 조건을 함께 검토한다. [데이터 통제](https://developers.openai.com/api/docs/guides/your-data)

4주차에는 선택한 Luna로 SEC 사실 카드의 분류·수치/기간 보존·한국어 요약·근거 연결·응답 시간·실제 토큰을 검증한다. 품질 미달은 보류·수정 대상으로 남기며 실제 사용권이 없는 기사 전문을 품질 시험에 넣지 않는다. 월 사용량 계산은 [비용 조사](월_비용.md)로 연결한다.

## 현재 검증 범위와 근거

### 로컬 검증 기록

스키마·모의 요청·파싱의 결과와 재현 명령은 [기술 조사 후속 검증](../../tasks/verification/integration/기술_조사_후속_검증.md#openai-계약-시험-상세)에 둔다. 이 계약 시험과 아래 실제 생성의 usage·지연을 구분한다.

### 실제 가상 자료 생성과 프롬프트 보완

2026-10-24 결제 후 `gpt-5.4-mini`로 직접 작성한 동일 가상 자료6건을 실행했다. 응답 모델은 `gpt-5.4-mini-2026-03-17`이다. `reasoning.effort=none`, `max_output_tokens=600`, `store=False`, 도구 없음·자동 재시도0 조건이며 캐시·추론 토큰은 기록상0이다. Marketaux 제3자 기사나 기사 전문을 이 시험에 전송하지 않았다.

| 시험 | 실제 입력 / 출력 토큰 | 단가 적용 비용 | 계획 환산 | 결과 근거 |
| --- | --- | --- | --- | --- |
| 동일 가상6건 | 1,866 / 804 | $0.0050175 | 약9.11원 | [원본 결과](../../tasks/verification/assets/news_samples/openai_after_credit_20261024.jsonl) |
| v2 범위·조건2건 | 745 / 266 | $0.00175575 | 약3.19원 | [후속 결과](../../tasks/verification/assets/news_samples/openai_scope_followup_20261024.jsonl) |
| 합계8건 | 2,611 / 1,070 | **$0.00677325** | **약12.29원** | 실제 usage × Mini 표준 단가 |

원화는 [월 비용](월_비용.md)의 1,815원/USD 계획 가정을 적용했으며 결제 명세의 확정 청구액이 아니다. 6건의 요청 지연은1.338~2.320초·합10.082초, 후속2건은1.376~3.163초·합4.539초다. 짧은 자료의 순차 실행 결과이므로 실제 기사·동시 실행의 지연 보장으로 쓰지 않는다.

첫6건은 선정4건·보류2건 및 기계 검사를 모두 통과했지만 에이전트 원문 대조에서 적용 범위 누락과 부정확한 보류 사유를 발견했다. `synthetic_summary_v2_scope_conditions`는 표본 원문·필수 문자열을 유지하고 적용 범위·확정/조건 보존, 이미 있는 날짜·값을 없다고 설명하지 않도록 지침만 보완했다. 원본6건 결과는 그대로 보존했다.

| 후속 표본 | 원문 대조 결과 | 남은 범위 |
| --- | --- | --- |
| 업종 | v2 요약에 업종 전반의 적용 범위가 복원됐고3%·확정일·시행일을 보존했다. 원문에 없는 구체 업종은 추가하지 않았다 | 해당 가상 표본에서의 개선이며 다른 범위 표현의 일반 성능은 미확인 |
| 조건 잘림 | 보류·빈 요약을 유지하고 예정일이 있음을 인정하며, 잘린 조건 때문에 개설 여부를 판단할 수 없다고 설명했다 | 실제 복잡한 조건·부정·후속 정정의 처리 품질은 미확인 |

이는 에이전트의 독립 대조이며 운영자 검토 완료가 아니다. 기계 검사는 출처 ID·근거 부분 문자열·필수 숫자/기간·한국어 포함 등을 확인할 뿐 의미 정확성을 보장하지 않는다. `USD million` 영문 표기는 실험의 literal 보존 지시에 따른 것이므로 수치 오역과 구분하며, 명사형·한국어 표현·출처·링크·X 길이를 갖춘 완성 게시문은 별도 검증한다. 짧은 가상8회 비용으로 월 AI 사용량 가정$1.0032를 대체하지 않는다.

### 접근·잔액 확인의 경계

현재는 실제 생성 성공으로 이용 가능만 확인했다. 현재 잔액·충전액·월 청구액을 조회한 것은 아니다. 공식 [오류 안내](https://developers.openai.com/api/docs/guides/error-codes)는 `credit_balance_exhausted`를 선불 크레딧 소진으로 구분하고 billing settings 확인을 안내한다. `insufficient_quota`라는 넓은 유형만으로 잔액·지출 상한 원인을 단정하지 않는다. 이전429 진단과 키 준비 전 조사 과정은 [별도 시험 이력](../../tasks/verification/news/뉴스_샘플과_요약_시험.md)에 보존하며 현재 생성·usage 미확보 상태로 표시하지 않는다.

### 공식 문서로 추가 확인한 내용

Mini는 `reasoning.effort=none`을 지원하므로 초기 요청에 명시해 추론 강도를 일정하게 둘 수 있다. 실제 요금이 0이 되거나 요약 품질을 보장한다는 뜻은 아니다. [모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini)

입력 토큰 사전 확인에는 `client.responses.input_tokens.count(...)`가 있으며 별도 사전 집계 요청은 실행하지 않았다. 실제 생성의 `usage.input_tokens`, `usage.output_tokens`는 위8건에서 확보했다. 청구 출력량은 눈에 보이는 문장 길이와 다를 수 있다. [토큰 계산 안내](https://developers.openai.com/api/docs/guides/token-counting)

Structured Outputs도 내용 오류가 가능하다고 공식 안내한다. 근거 부족·거절·출력 상한 도달·미완료 응답은 검증 실패로 처리해야 한다. [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs)

### 남은 최소 시험

1. 가상 자료 원문·결과를 운영자가 검토하고 범위·조건·수치·보류 사유 및 X 완성문 형식의 평가 기준을 확정한다.
2. Fed·BLS·BEA·SEC의 지원 발표 유형별 허용 근거를 확보하고 공통 입력 계약에 연결한다. 외부 AI 입력과 공개 요약은 자료별 이용 범위를 확인하며 수집 완료·근거·비용을 검증한다. [뉴스 수집](뉴스_수집.md)
3. 허용된 실제 기사·공시 사실 카드로 Luna의 source ID·숫자·단위·기간·범위·조건 보존과 제외 사유를 검증한다.
4. 실제 운영 길이·후보 수·재처리의 usage·지연을 기록한 뒤 월 비용 가정을 갱신한다. 잔액·청구액은 계정의 billing 기록으로 별도 확인한다.

무료 뉴스 API 접근이나 가상 요약 성공은 실기사 공개 이용·외부 AI 전달·운영 비용 충족을 보장하지 않는다. 공개 문서와 작은 가상 표본만으로 실뉴스 품질·청구액을 확정하지 않는다.
