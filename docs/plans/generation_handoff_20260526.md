# RFP RAG Generation Handoff - 2026-05-26

## 1. 현재 작업 위치

- Repository: `yoosy0125/chatbot`
- Working branch: `rag`
- Generation notebook: `notebooks/rag/rfp_generation_p4_hwpx_quickcheck.ipynb`
- Generation module: `src/generation/rfp_generation.py`
- 최신 분석 대상 결과 폴더:
  - `outputs/generation_review50_J5_hybrid_rrf_rerank_20260526_021047`

`outputs/`는 `.gitignore` 대상이므로 결과 원본은 Git에 올리지 않는다. 이 문서는 다른 컴퓨터에서 이어서 보기 위한 요약/분석 기록이다.

## 2. 이번 Generation 파트에서 구현한 핵심

### 2.1 Field-aware context 구성

Retrieval 결과를 그대로 LLM에 모두 넣지 않고, 질문 유형과 JSON key를 기준으로 context를 재구성한다.

주요 활용 필드:

- `source_file`, `doc_id`, `chunk_id`, `evidence_id`
- `chunk_type`, `fact_type`, `section_path`
- `fact_candidates`
- `project_name`, `issuer`
- `answer_policy`, `*_answer_enabled`
- `target_slots`, `intent_slots`, `intent_plan`

핵심 의도는 다음과 같다.

```text
retrieval은 넓게 가져오고,
generation은 질문 의도에 맞는 field만 골라서 사용한다.
```

### 2.2 질문 의도 분해

하나의 질문에 여러 요청이 섞여 있을 수 있어서 단일 `answer_type`만으로는 부족했다. 그래서 아래 구조를 추가했다.

- `target_slots`: 질문에서 요구하는 대상 문서/사업/기관 후보
- `intent_slots`: 질문 안의 하위 의도 목록
- `intent_plan`: LLM에게 전달할 실행 계획

예시:

```text
Q100: 예산 + 핵심 요약
=> budget_lookup + purpose_summary

Q214: 두 예산 합계 + 사업 성격 차이 설명
=> budget_sum + multi_doc_comparison
```

### 2.3 Deterministic numeric layer

차액, 합계, 비율처럼 계산이 필요한 질문은 LLM에게 계산을 맡기지 않고 코드에서 계산하도록 설계했다.

- 질문 안에 이미 숫자가 있으면 operand로 사용
- context에서 target별 금액이 확인되면 operand로 사용
- 계산 결과는 `computed_values`에 저장
- LLM은 계산값을 문장화하는 역할에 가깝게 제한

### 2.4 JSON 파싱 실패 복구

이전 실험에서는 LLM 출력 JSON이 길어지며 잘려 `answer`가 빈 값으로 처리되는 문제가 있었다. 지금은 다음처럼 보완했다.

- LLM 출력 schema를 줄임
- citation은 LLM이 직접 길게 쓰지 않고 코드가 붙임
- JSON 파싱 실패 시 raw text에서 `answer`를 복구
- 복구 여부를 `recovered_answer`, `parse_error_type`에 기록

### 2.5 RAGAS 입력 경로 정리

RAGAS가 예전 결과 폴더를 보는 문제가 있었다. 최신 노트북에서는 `ragas_eval_input.jsonl` 후보를 스캔하고, empty answer가 가장 적은 파일을 우선 선택하도록 정리했다.

정상 확인 기준:

```text
empty answer rows: 0
```

## 3. 최신 실험 설정

결과 폴더: `outputs/generation_review50_J5_hybrid_rrf_rerank_20260526_021047`

| 항목 | 값 |
|---|---|
| corpus | `parsing_p4_hwpx_125_datafix_recallguard` |
| retrieval run | `exp100_0525_exp1_recallguard_docfill_metadatafilter` |
| retrieval method | `J5_hybrid_rrf_rerank` |
| generation model | `Qwen/Qwen2.5-3B-Instruct` |
| sample size | 50 |
| source_store | `False` |
| max context chars | 8000 |
| max new tokens | 1024 |
| decoding | greedy, `do_sample=False` |
| RAGAS judge | `gpt-5-nano` |
| RAGAS evaluated rows | 10 |

## 4. 최신 실험 주요 수치

### 4.1 Deterministic metrics

| 지표 | 값 | 해석 |
|---|---:|---|
| total questions | 50 | review50 기준 |
| valid JSON rate | 0.96 | 48/50은 정상 JSON |
| empty answer rate | 0.00 | 빈 답변 문제는 해결됨 |
| recovered answer rate | 0.04 | 2건은 raw text에서 복구 |
| citation valid rate | 0.94 | citation 구조는 대체로 안정 |
| source numeric grounded rate | 0.86 | 숫자 근거 선택은 아직 취약 |
| derived numeric valid rate | 1.00 | 코드 계산 레이어 자체는 정상 |
| answerable rate | 0.80 | 10건은 insufficient/not_found 처리 |
| avg generation time | 약 11.49초/문항 | 50문항 기준 평균 |

### 4.2 Failure tag 상위 항목

| failure tag | count | 의미 |
|---|---:|---|
| `multi_intent_incomplete` | 15 | 복합 질문에서 일부 의도 누락 |
| `source_numeric_missing` | 14 | target 문서의 숫자 근거를 확정하지 못함 |
| `target_doc_coverage_missing` | 10 | multi-doc 질문에서 target 문서 coverage 부족 |
| `llm_hallucination_risk` | 7 | context 밖 추론 또는 근거 약한 서술 가능성 |
| `insufficient_evidence` | 3 | 답변 근거 부족 |
| `citation_wrong_target` | 2 | citation이 질문 대상 문서와 어긋남 |
| `llm_invalid_json` | 2 | JSON 파싱 실패 후 복구됨 |
| `wrong_target_field_selection` | 1 | target과 다른 field 선택 |

### 4.3 RAGAS smoke 결과

RAGAS는 10개 샘플만 평가했다. 전체 성능 확정값이 아니라 방향성 확인용이다.

| 지표 | 평균 |
|---|---:|
| faithfulness | 0.346 |
| answer relevancy | 0.732 |
| context precision | 0.585 |
| context recall | 0.400 |

해석:

- 답변 형식과 빈 답변 문제는 개선됐다.
- 하지만 RAGAS 기준으로는 context recall과 faithfulness가 낮다.
- 특히 예산/복합 질문에서 target 문서의 정확한 숫자 근거를 못 잡는 문제가 크다.

## 5. 주요 실패사례 분석

### Q008 - 예산 차액 질문

GT:

```text
2,392,940,000원 - 1,247,000,000원 = 1,145,940,000원
```

현재 결과:

```text
한국수자원공사 target 예산 근거를 context에서 확인할 수 없어 계산 불가
```

분석:

- 과거에는 다른 한국수자원공사 사업의 `495,000,000원`을 잘못 가져왔다.
- 이번 버전에서는 잘못된 대체값을 막고 `insufficient_context`로 처리했다.
- 방향은 좋아졌지만, 실제 target 문서 안에 있는 `2,392,940,000원`을 budget fact로 확정하지 못했다.

필요 보완:

- target 문서 내 text/table에서 예산 label을 재탐색하는 fallback 필요
- `project_budget` 후보가 없더라도 target 문서 안의 `사업예산`, `용역비`, `총사업비` 주변 금액을 후보로 승격해야 함

### Q021 - 정답을 알고도 postprocess가 거부한 사례

GT:

```text
5,031,000,000원
```

LLM parsed answer:

```text
5,031,000,000원
```

최종 answer:

```text
사업예산 근거를 context에서 확인할 수 없어 계산할 수 없습니다.
```

분석:

- LLM은 맞는 값을 생성했다.
- 하지만 postprocess의 `target_project_budget_missing` guard가 너무 엄격해서 최종 답변을 거부했다.

필요 보완:

- LLM 값이 citation text 안에 실제로 존재하면 낮은 confidence라도 통과시키는 검증 로직 필요
- `source_numeric_missing`을 단순 실패가 아니라 `source_numeric_found_in_text_but_not_fact`로 세분화할 필요가 있음

### Q201 - `전체 배정액`과 일반 예산 구분 실패

GT:

```text
780,230,000원
```

현재 답변:

```text
2억원
```

분석:

- 질문은 단순 `사업예산`이 아니라 `전체 배정액`을 묻는다.
- 현재 budget 후보는 금액 label의 의미를 충분히 구분하지 못한다.
- `2억원`은 표 내부의 다른 기준/임계값 성격일 가능성이 높다.

필요 보완:

```json
{
  "amount": "780,230,000원",
  "budget_type": "total_allocation",
  "label": "전체 배정액",
  "evidence": "..."
}
```

### Q214 - 계산은 맞지만 복합 설명이 약한 사례

GT 핵심:

```text
합계 1,080,945,000원.
울산 버스정보시스템은 시민/B2C 편의,
생기원 전자조달은 조달 업체/B2B 편의.
```

현재 답변:

```text
합계는 맞음.
하지만 B2C/B2B 설명이 일반론적이고 근거가 약함.
```

분석:

- 계산 부분은 비교적 성공했다.
- 하지만 두 번째 intent인 사업 성격 비교가 일반론으로 흘렀다.
- citation 중 일부가 target과 맞지 않는 문서를 포함했다.

필요 보완:

- `budget_sum`과 `business_character_comparison`을 분리해야 함
- 각 target 문서에서 `사업목적`, `추진배경`, `대상 사용자`, `서비스 대상` context를 별도 주입해야 함
- LLM prompt에서 일반 B2C/B2B 정의가 아니라 context 근거 기반으로만 비교하게 제한해야 함

### Q100 - 예산은 맞지만 요약이 얕은 사례

GT 핵심:

```text
2,349,130,320원.
R&D 검증 소요시간 단축, 기업 지원 생산 아웃풋 강화.
```

현재 답변:

```text
예산은 맞음.
요약은 R&D 역량 강화 수준으로 뭉뚱그려짐.
```

분석:

- `budget_lookup + purpose_summary` 분해는 됐다.
- 하지만 purpose_summary에 필요한 현장/팩토리/아웃풋 context가 충분히 들어가지 않았다.
- citation도 target과 맞지 않는 문서가 섞였다.

필요 보완:

- 복합 질문에서 각 intent마다 별도 evidence block을 구성해야 함
- `현장`, `R&D`, `검증`, `생산`, `기업지원`, `팩토리`, `아웃풋` 같은 도메인 키워드를 purpose/requirement context 선택에 반영

### Q057 - 부정 답변은 맞지만 상태 관리가 아쉬운 사례

현재 답변:

```text
명확한 요구사항은 발견되지 않았습니다.
```

분석:

- 답변 내용은 GT와 큰 방향이 맞다.
- 하지만 `missing_intent:negative_check`가 남았다.
- 부정형/없음 답변을 정상 답변으로 관리하는 로직이 아직 부족하다.

필요 보완:

- `answer_status=not_found_in_context` 또는 `negative_answer_confirmed`를 별도 사용
- 확인한 문서/섹션을 `checked_citations`로 남김
- “없다” 답변은 hallucination risk가 아니라 확인된 부정 답변으로 관리

## 6. 현재 상태에 대한 판단

### 좋아진 점

- 빈 답변 문제는 해결됐다.
- JSON 파싱 실패도 2건만 발생했고, 모두 복구됐다.
- 계산형 질문에서 deterministic layer가 작동하기 시작했다.
- 잘못된 예산 대체를 막는 guard가 들어가면서, 틀린 값을 자신 있게 답하는 위험은 줄었다.
- `review_samples.csv`, `llm_answer_review.csv/html`, `ragas_per_question.csv`가 생성되어 사람이 보기 쉬워졌다.

### 아직 약한 점

- target 문서 안의 숫자를 fact로 확정하지 못하는 경우가 많다.
- budget 후보의 의미 구분이 부족하다. 특히 `전체 배정액`, `사업예산`, `추정가격`, `평가 기준 금액`, `지급조건`이 섞인다.
- 복합 질문에서 한 intent는 답하지만 다른 intent는 얕게 처리하는 경우가 있다.
- citation이 최종 답변 target과 어긋나는 경우가 남아 있다.
- source_store를 아직 사용하지 않아서 긴 근거 확장이 제한된다.

## 7. 다음 작업 우선순위

### 1순위: budget candidate type 세분화

```json
{
  "amount": 780230000,
  "raw_amount": "780,230,000원",
  "budget_type": "total_allocation",
  "label": "전체 배정액",
  "source_file": "...",
  "evidence_id": "...",
  "confidence": "medium"
}
```

질문에 `전체 배정액`, `총사업비`, `사업예산`, `추정가격`, `차수`, `지급` 같은 qualifier가 있으면 동일 type 후보를 우선 선택한다.

### 2순위: target-aware numeric fallback

`fact_candidates`에 확정 예산이 없더라도 target 문서 text/table 안에 label+amount가 있으면 fallback 후보로 사용한다.

단, 다른 문서나 같은 기관의 다른 사업 금액으로 대체하지 않는다.

```text
target 문서 안 금액 있음 -> low/medium confidence 후보
다른 문서 금액만 있음 -> missing 처리
```

### 3순위: intent별 context package 분리

현재 context는 질문 전체 기준으로 묶이는 경향이 있다. 복합 질문은 intent별로 context를 나눠야 한다.

```text
I01 budget_sum -> 예산 fact/table만
I02 business_character_comparison -> 사업목적/대상사용자/추진배경만
```

### 4순위: citation reranking

답변 생성 후 citation을 다시 고른다.

우선순위:

1. target source_file 일치
2. required fact_type 일치
3. answer_policy 허용
4. evidence_text 안에 답변 숫자/핵심 표현 포함
5. backfill 문서는 후순위

### 5순위: negative answer 상태 분리

“문서에 없음”은 실패가 아니다. 다음 필드를 추가하거나 강화한다.

- `answer_status=not_found_in_context`
- `negative_answer_confirmed=True`
- `checked_citations`

## 8. 다른 컴퓨터에서 이어서 작업하는 방법

1. 최신 코드 받기

```bash
git pull origin rag
```

2. generation 노트북 열기

```text
notebooks/rag/rfp_generation_p4_hwpx_quickcheck.ipynb
```

3. 경로 확인

상단 설정에서 아래 값 확인:

```python
CORPUS_N = 125
PARSING_OUTPUT_NAME = "parsing_p4_hwpx_125_datafix_recallguard"
RUN_NAME = "exp100_0525_exp1_recallguard_docfill_metadatafilter"
RETRIEVAL_EXPERIMENT_ID = "J5_hybrid_rrf_rerank"
USE_SOURCE_STORE = False
```

4. RAGAS만 다시 볼 때

실행 순서:

```text
36번 셀: RAGAS 입력 후보 확인 및 선택
38번 셀: python-dotenv 설치
39번 셀: .env / RAGAS 설정
40번 셀: RAGAS 실행
41번 셀: 결과 확인
```

36번 셀에서 아래처럼 보여야 정상:

```text
empty answer rows: 0
```

5. 사람이 직접 봐야 할 파일

결과 폴더에서 우선순위:

```text
llm_answer_review.html
llm_answer_review.csv
review_samples.csv
metrics_summary.json
failure_tags_summary.json
ragas_per_question.csv
```

## 9. 다음 실험 목표

다음 generation 실험은 단순 평균 점수 상승보다 아래 항목 개선을 목표로 한다.

- Q201 같은 `전체 배정액` 질문에서 정확한 budget type 선택
- Q214 같은 예산+성격 비교 복합 질문에서 intent별 답변 완성
- Q008/Q021처럼 target 문서 숫자가 있는데도 `source_numeric_missing`이 뜨는 문제 축소
- citation_wrong_target 감소
- RAGAS context_recall / faithfulness 개선

권장 성공 기준:

```text
empty_answer_count = 0 유지
valid_json_rate >= 0.96 유지
source_numeric_grounded_rate >= 0.90
multi_intent_incomplete 감소
target_doc_coverage_missing 감소
RAGAS context_recall 0.40 -> 0.60 이상
```
