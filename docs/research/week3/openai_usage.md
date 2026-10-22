# R4 · OpenAI 활용과 모델 비교

- 확인일: 2026-10-22, Asia/Seoul
- 범위: 공식 문서 조사. API 호출·모델 품질/지연 실측·결제는 수행하지 않음
- 기준: [조사계획](../../../tasks/week3_research_plan.md)

## 결론

공식 Python SDK의 Responses API와 Pydantic 구조화 출력을 사용하는 단순한 단계별 파이프라인을 우선 추천한다. 별도 에이전트 프레임워크·자율 웹 탐색·벡터 DB를 첫 버전의 필수 요소로 추가할 이유는 현재 흐름에서 발견하지 못했다. 이는 설계 판단이며 실측 성능 우위를 뜻하지 않는다. SDK 사용법은 [공식 SDK 안내](https://developers.openai.com/api/docs/libraries)에서 확인했다.

## 모델 후보와 가격

표는 일반 텍스트 100만 토큰당 USD 입력/출력 단가다. 캐시·Batch·특수 처리 할인은 계산하지 않았다. 계정 접근과 호출 한도는 실제 프로젝트에서 별도 확인해야 한다.

| 후보 | 입력 | 출력 | 조사 판단 |
| --- | --- | --- | --- |
| GPT-5.4 Mini | $0.75 | $4.50 | 우선 시험 후보. Responses·Structured Outputs 지원 확인, 한국어 품질은 미시험 |
| GPT-5.6 Terra | $2.00 | $12.00 | 비교 후보. 비용과 품질 향상의 실익을 같은 샘플로 평가 |
| GPT-5.4 nano | $0.20 | $1.25 | 저가 비교 자료로 기록. 공식 페이지 Deprecated 표시로 신규 채택 보류 |

근거: [Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano). GPT-5 Mini도 [모델 페이지](https://developers.openai.com/api/docs/models/gpt-5-mini)에 Deprecated 표시가 있어 저렴하다는 이유만으로 선택하지 않는다. 최신 전체 가이드는 [Using GPT-6](https://developers.openai.com/api/docs/guides/latest-model)로 연결되지만, 최신 모델 전체를 반드시 채택해야 한다는 의미는 아니다. 모델 종료 일정은 구현 시작 때 재확인한다.

## 기능별 적용

| 단계 | AI 작업 | Python·운영자 작업 |
| --- | --- | --- |
| 수집 후 필터 | 기사 분류·관련성·사건 중요성 설명·근거 추출 | 관찰 기업·시각·기사 ID·중복의 확실한 조건을 먼저 필터 |
| 후보 생성 | 선택 자료를 한국어 요약·명사형 X 초안으로 작성 | 지수 등락률 계산, 값·단위·기간·URL 연결 |
| 검증 | 게시문과 근거의 모순·근거 누락 표시 | 원본 숫자·날짜·길이·중복·마감·승인·한도 검사 |
| 게시 결정 | 매매 지시나 근거 없는 전망을 생성하지 않도록 지침 적용 | 운영자가 원문·초안 검토 후 승인 |

AI 검증 실패 시 기존 정책대로 1회 재생성·재검증 후 보류한다. 같은 모델의 재검사는 독립적인 사실 보증이 아니며 최종 운영자 확인을 유지한다. 기사 본문은 지시가 아닌 분석 대상으로 전달하고, 기사 안의 명령을 도구 실행·게시 승인으로 해석하지 않도록 한다.

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
    model="gpt-5.4-mini",
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

4주차에는 같은 허용 기사 샘플로 Mini·Terra의 분류·수치/기간 보존·한국어 요약·근거 연결·응답 시간·실제 토큰을 비교한다. 실제 사용권이 없는 기사 전문을 품질 시험에 넣지 않는다. 월 사용량 계산은 [비용 조사](monthly_cost.md)로 연결한다.

## 후속 확인 · 공개 자료와 로컬 시험

2026-10-22 사용자는 계정·키가 아직 없으며 공개 자료·로컬 검증부터 진행하도록 답했다. 현재 프로세스의 OpenAI 키 존재 여부만 확인했고 실제 비밀 값은 읽거나 출력하지 않았다. 아래 결과는 모델 실행 성능과 구분한다.

### 실제 실행한 검증

[오프라인 검증 스크립트](experiments/openai_contract_probe.py)를 기존 `.venv` Python으로 실행했다. `httpx.MockTransport`가 모든 요청을 메모리에서 처리하므로 외부 API와 실제 키를 사용하지 않는다.

```powershell
.venv/Scripts/python.exe docs/research/week3/experiments/openai_contract_probe.py
```

| 확인 항목 | 실행 결과 |
| --- | --- |
| 설치 버전 | openai 3.26.0, pydantic 2.13.5, httpx 0.28.1 |
| SDK 계약 | responses.parse·text_format·strict JSON Schema 생성과 모의 결과의 output_parsed 확인 |
| 요청 제어 | store=False·reasoning none·출력 상한·도구 없음·SDK 재시도0 설정이 요청에 들어감 |
| 형식 오류 | boolean 문자열·허용 범주 밖 분류·미승인 필드 등 3개 입력 거부 |
| 사실 오류 | 10 billion을 999 billion으로 바꿔도 스키마는 수용. 스키마가 사실 검증을 대신하지 못함을 확인 |
| 근거 연결 | 가상 근거가 입력 자료에 없음을 별도 검사로 탐지. 완전한 의미 검증기는 아님 |

모의 응답의 usage=100/40은 시험용 숫자이며 실제 토큰 측정값이 아니다. 한국어 생성 품질·모델 지연·요금제별 접근·실제 usage는 키 없이 검증하지 못했다.

### 공식 문서로 추가 확인한 내용

Mini는 `reasoning.effort=none`을 지원하므로 초기 요청에 명시해 추론 강도를 일정하게 둘 수 있다. 실제 요금이 0이 되거나 요약 품질을 보장한다는 뜻은 아니다. [모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini)

입력 토큰 확인에는 `client.responses.input_tokens.count(...)`가 있으며 실제 생성 결과는 `usage.input_tokens`, `usage.output_tokens`로 기록한다. 청구 출력량은 눈에 보이는 문장 길이와 다를 수 있다. 정확한 서버 측 집계는 인증 요청이 필요하므로 현재 미실행이다. [토큰 계산 안내](https://developers.openai.com/api/docs/guides/token-counting)

Structured Outputs도 내용 오류가 가능하다고 공식 안내한다. 근거 부족·거절·출력 상한 도달·미완료 응답은 검증 실패로 처리해야 한다. [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs)

### 계정 준비 후 남은 최소 시험

1. OpenAI 프로젝트 생성·모델 접근·잔액/과금 조건을 확인하고 키는 로컬 환경변수로 설정한다.
2. 기사 이용 조건을 확인한 샘플 또는 직접 만든 한국어·영어 자료로 분류·요약을 실제 실행한다. 유료 시험 사용량은 실행 전 확인한다.
3. 실제 source ID·숫자·단위·기간·조건문 보존, 근거 없는 인과관계, 제외 사유를 운영자가 판정한다.
4. 호출별 모델·usage·응답 시간·거절/미완료와 검증 결과를 남기고 월 비용 가정을 교체한다.

현재 미확인 항목은 위 계정과 자료 사용권이 있어야 확인할 수 있으며, 공개 문서 조사만 반복해 품질·청구액을 확정하지 않는다.
