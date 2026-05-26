# Generation Module README

이 폴더는 RFP RAG 파이프라인의 generation 단계에서 검색 결과를 LLM 답변용 context로 재구성하고, 답변 후처리/검수 산출물을 만드는 유틸리티를 담고 있습니다.

현재 핵심 파일은 두 개입니다.

| 파일 | 역할 |
|---|---|
| `rfp_generation.py` | 질문 분류, context package 생성, prompt 생성, LLM 답변 후처리, review/RAGAS 입력 산출물 저장 |
| `__init__.py` | 노트북이나 외부 코드에서 자주 쓰는 public 함수들을 한 번에 import할 수 있게 노출 |

## 왜 수정했는가

초기 `llm_answer_review.html` 50개 검토에서 가장 크게 보였던 문제는 단순히 "LLM이 답을 못 한다"가 아니었습니다. Raw LLM text 안에는 답이 들어 있는데도 JSON이 길어지면서 잘리거나, citation과 긴 evidence text까지 LLM이 직접 생성하려다 최종 `answer`가 빈 값으로 저장되는 문제가 있었습니다.

그래서 수정 방향은 단순 prompt 변경이 아니라 다음 구조 개선이었습니다.

1. LLM에게는 짧은 답변 JSON만 생성하게 한다.
2. citation, evidence id, failure tag, 계산값은 코드가 붙인다.
3. 예산/기간/제출서류/자격요건 등 질문 유형별로 필요한 JSON key를 context 앞쪽에 재배치한다.
4. 차액, 합계, 비율 같은 계산은 LLM이 아니라 deterministic code layer에서 처리한다.
5. JSON 파싱 실패 시 raw text에서 answer를 복구하고, 복구 여부를 review 산출물에 남긴다.

이 변경의 목적은 답변을 더 화려하게 만드는 것이 아니라, 답변이 최종 파일에 안정적으로 남고 사람이 검수 가능한 구조를 만드는 것입니다.

## review50에서 본 실제 사례와 수정 방식

아래 내용은 초기 50개 검토에서 보였던 문제를 기준으로, 어떤 로직을 왜 넣었는지 인수인계용으로 정리한 것입니다. 모든 항목이 완전히 해결됐다는 뜻은 아니고, "어떤 문제를 막기 위해 어떤 구조를 추가했는지"를 설명합니다.

| 검토 사례 | 관찰된 문제 | 넣은 로직/수정 방향 | 현재 상태 |
|---|---|---|---|
| raw LLM text 안에는 답이 있는데 final answer가 빈 값으로 저장되는 사례 | LLM이 answer, citation, 긴 evidence text를 한 JSON에 모두 쓰면서 출력이 잘리거나 JSON 파싱이 실패함 | LLM 출력 schema를 줄이고, citation/evidence id/failure tag는 `postprocess_answer()`와 `save_generation_outputs()`가 붙이도록 분리. invalid JSON이면 `_recover_partial_answer_fields()`로 answer를 복구하고 `_recovered_answer`를 남김 | review50 기준 empty answer rate 0.00, recovered answer 2건 |
| 예산 + 사업 요약을 같이 묻는 복합 질문, 예: Q100 | 질문은 "예산은 얼마이고 핵심은 무엇인지"를 묻는데, 답변이 예산만 말하거나 요약이 너무 일반적으로 흐름 | `classify_question()`에서 `intent_slots`를 만들고, `budget_lookup + purpose_summary`처럼 질문 안의 하위 의도를 분리. `_build_intent_plan()`으로 LLM에게 답변 섹션 순서를 전달하고, prompt에 `예산:\n핵심 요약:\n근거:` 형식을 명시 | 예산 누락은 줄었지만, 요약에 필요한 `사업목적/추진배경/대상 사용자` context 선별은 추가 개선 필요 |
| 두 문서 예산 합계 + 사업 성격 비교를 같이 묻는 질문, 예: Q214 | 합계 계산은 되더라도 B2C/B2B 성격 비교가 일반론으로 흐르거나, citation이 target과 다른 문서를 가리킴 | 계산은 `_compute_deterministic_values()`가 `computed_values`로 만들고, LLM은 계산값을 문장화하도록 제한. 동시에 `intent_plan`에 `budget_sum`과 `business_character_comparison`을 분리해서 둘 다 답하도록 요구 | 계산 레이어는 정상 작동. 다만 비교 설명용 evidence를 예산 evidence와 별도로 구성하는 작업이 남음 |
| 예산 차액 질문, 예: Q008 | target 문서의 예산을 못 찾으면 같은 기관/비슷한 사업의 다른 금액을 가져와 틀린 계산을 할 위험이 있었음 | `target_slots`로 질문의 대상 문서/사업을 잡고, `matched_source_file`이 맞는 근거만 최종값으로 쓰도록 guard 추가. target 문서 금액이 확정되지 않으면 다른 문서 값으로 대체하지 않고 `insufficient_context`로 처리 | 틀린 값을 자신 있게 답하는 위험은 줄었지만, target 문서 안에 있는 숫자를 fallback으로 찾는 로직은 더 필요 |
| LLM은 맞는 값을 냈지만 postprocess가 거부한 사례, 예: Q021 | raw/parsed answer에는 `5,031,000,000원`이 있었는데, source numeric guard가 너무 엄격해서 최종 answer가 "근거 확인 불가"로 바뀜 | `_source_numeric_grounded`, `source_numeric_missing`, `gt_expected_answer_but_model_not_found` 같은 진단 태그를 남겨서 "LLM 오류"와 "후처리 guard 오류"를 구분 가능하게 함 | 아직 완전 해결 아님. citation text 안에 답 숫자가 실제로 있으면 낮은 confidence로 통과시키는 보완 필요 |
| `전체 배정액` 질문, 예: Q201 | 질문은 전체 배정액을 묻는데, 일반 사업예산/기초금액/지급조건 금액과 섞여 잘못된 값을 고를 수 있음 | `FINAL_BUDGET_FACT_TYPES`, `BUDGET_BLOCKED_FACT_TYPES`, budget context keyword를 나눠서 최종 예산으로 쓸 수 있는 금액과 쓰면 안 되는 금액을 분리하기 시작함 | `total_allocation`, `estimated_price`, `base_amount`, `payment_terms` 같은 budget type 세분화가 다음 작업 |
| "문서에 없음"을 답해야 하는 부정형 질문, 예: Q057 | 실제로 없는 요구사항이면 "없다"가 정답일 수 있는데, 기존에는 실패처럼 보이거나 hallucination risk와 섞임 | prompt와 후처리에 `answer_status=not_found_in_context` 개념을 넣고, not-found 답변을 별도 상태로 관리하도록 방향 설정 | checked evidence/citation을 더 명확히 남기는 개선 필요 |

핵심은 각 사례를 "프롬프트 문장 하나 고침"으로 처리하지 않았다는 점입니다. 질문을 intent로 나누고, target 문서를 고정하고, 계산은 코드가 맡고, 후처리는 citation과 진단 태그를 붙이는 식으로 책임을 분리했습니다.


## 개선 확인 기준

최신 handoff 기준 `outputs/generation_review50_J5_hybrid_rrf_rerank_20260526_021047`에서 확인한 주요 수치는 다음과 같습니다.

| 지표 | 값 | 의미 |
|---|---:|---|
| total questions | 50 | review50 기준 |
| valid JSON rate | 0.96 | 48/50은 정상 JSON |
| empty answer rate | 0.00 | 빈 답변 문제는 해결 |
| recovered answer rate | 0.04 | 2건은 raw text에서 복구 |
| citation valid rate | 0.94 | citation 구조는 대체로 안정 |
| source numeric grounded rate | 0.86 | 숫자 근거 선택은 아직 보완 필요 |
| derived numeric valid rate | 1.00 | 코드 계산 레이어는 정상 작동 |

RAGAS는 10개 샘플 smoke test만 돌렸으므로 전체 성능 확정값이 아닙니다. 방향성 확인용으로만 봅니다.

| RAGAS 지표 | 평균 |
|---|---:|
| faithfulness | 0.346 |
| answer relevancy | 0.732 |
| context precision | 0.585 |
| context recall | 0.400 |

요약하면, 빈 답변과 JSON 저장 안정성은 개선됐고, 아직 남은 문제는 target 문서의 정확한 숫자 근거 선택, 복합 질문 intent 누락, citation target mismatch 쪽입니다.

## 전체 흐름

일반적인 노트북 흐름은 아래 순서입니다.

```python
from src.generation import (
    build_context_package,
    build_prompt,
    enrich_generation_record,
    load_chunk_index,
    load_generation_input_rows,
    postprocess_answer,
    prepare_generation_items,
    save_generation_outputs,
)
```

1. retrieval 결과와 context row를 읽습니다.
2. 필요한 chunk JSONL을 `load_chunk_index()`로 index화합니다.
3. `prepare_generation_items()`로 실험 ID와 sample size에 맞는 질문 단위 item을 만듭니다.
4. 각 질문마다 `build_context_package()`를 호출합니다.
5. `build_prompt()`로 LLM 입력 메시지를 만듭니다.
6. LLM raw output을 `postprocess_answer()`로 정규화합니다.
7. `enrich_generation_record()`로 질문/근거/진단 필드를 합칩니다.
8. `save_generation_outputs()`로 review 파일과 RAGAS 입력 파일을 저장합니다.

간단한 형태는 다음과 같습니다.

```python
result_rows, context_rows = load_generation_input_rows(results_path, context_path)
items = prepare_generation_items(
    result_rows,
    context_rows,
    experiment_id="J5_hybrid_rrf_rerank",
    sample_size=50,
)

chunk_index = load_chunk_index(chunks_path)
records = []

for item in items:
    context_package = build_context_package(
        item["question"],
        item["retrieved_contexts"],
        chunk_index=chunk_index,
        use_source_store=False,
    )
    messages = build_prompt(context_package)
    raw_text = run_llm(messages)
    answer = postprocess_answer(raw_text, context_package)
    records.append(
        enrich_generation_record(
            answer,
            item,
            context_package,
            model_name="Qwen/Qwen2.5-3B-Instruct",
            experiment_name="J5_hybrid_rrf_rerank",
        )
    )

save_generation_outputs(output_dir, records, run_config={"sample_size": 50})
```

`run_llm()`은 노트북에서 사용하는 모델 호출 함수로 대체하면 됩니다.

## `__init__.py`에서 가져다 쓰는 주요 함수

`src/generation/__init__.py`는 아래 함수들을 외부에 노출합니다.

### 입력 로딩

| 함수 | 사용 목적 |
|---|---|
| `read_jsonl(path)` | JSONL 파일 읽기 |
| `read_csv_records(path)` | CSV 파일을 dict row 목록으로 읽기 |
| `load_generation_predictions_jsonl(path)` | prediction JSONL에서 result/context row 분리 |
| `load_generation_input_rows(results_path, context_path=None)` | generation 입력 row 로딩 |
| `inspect_jsonl_structure(path)` | JSONL 구조와 canonical field mapping 확인 |

### index 로딩

| 함수 | 사용 목적 |
|---|---|
| `load_chunk_index(chunks_path, ...)` | `chunk_id -> chunk record` index 생성 |
| `load_source_store_index(source_store_path, enabled=False)` | source_store 원문 index 생성. 기본은 사용 안 함 |

현재 team-share 기본 모드는 `source_store`를 사용하지 않습니다. `source_store`는 나중에 근거 확장을 위해 붙일 수 있는 선택 경로이고, embedding target은 아닙니다.

### 질문/context/prompt

| 함수 | 사용 목적 |
|---|---|
| `classify_question(question)` | 예산, 기간, 제출서류, 복합 비교 등 질문 유형 분석 |
| `prepare_generation_items(...)` | retrieval 결과를 질문 단위 generation item으로 변환 |
| `build_context_package(...)` | 질문 유형과 JSON key를 기준으로 LLM context 구성 |
| `build_prompt(context_package)` | system/user prompt 메시지 생성 |

`build_context_package()`는 검색 결과를 그대로 LLM에 던지지 않습니다. 질문 유형에 맞는 `fact_candidates`, `answer_policy`, `target_slots`, `intent_plan`, `computed_values`를 앞쪽에 배치합니다.

### 답변 후처리

| 함수 | 사용 목적 |
|---|---|
| `postprocess_answer(raw_text, context_package)` | LLM raw output JSON 파싱, schema 정규화, citation 자동 부착, failure tag 생성 |
| `enrich_generation_record(answer, item, context_package, ...)` | 질문, context, 답변, 진단 필드를 하나의 record로 병합 |

`postprocess_answer()`에서 처리하는 주요 보완은 다음과 같습니다.

- invalid JSON 복구
- deterministic calculation 결과 적용
- citation 자동 부착
- numeric grounding 검증
- answer policy 검증
- multi-intent 누락 감지
- wrong target citation 감지

### 산출물 저장과 검수

| 함수 | 사용 목적 |
|---|---|
| `create_generation_summary(records)` | JSON 안정성, 빈 답변, citation, numeric grounding 등 summary 생성 |
| `build_review_rows(records)` | 사람이 볼 review CSV row 생성 |
| `build_llm_answer_review_rows(records)` | raw LLM text와 final answer 비교용 row 생성 |
| `write_llm_answer_review_html(path, rows)` | 검토용 HTML 생성 |
| `build_ragas_eval_records(records)` | RAGAS 입력 JSONL row 생성 |
| `save_generation_outputs(output_dir, records, run_config=...)` | generation 결과 파일 일괄 저장 |
| `summarize_ragas_scores(rows)` | RAGAS per-question 결과 요약 |

`save_generation_outputs()`가 만드는 주요 파일은 다음과 같습니다.

| 파일 | 용도 |
|---|---|
| `generated_answers.jsonl` | 최종 generation record |
| `review_samples.csv` | 사람이 빠르게 보는 검토용 표 |
| `llm_answer_review.csv` | raw/parsed/final answer 비교용 CSV |
| `llm_answer_review.html` | 팀 공유 및 수동 검수용 HTML |
| `metrics_summary.json` | deterministic metrics summary |
| `failure_tags_summary.json` | failure tag별 count와 예시 |
| `ragas_eval_input.jsonl` | RAGAS 입력 |
| `ragas_metrics_summary.json` | RAGAS 요약 |
| `ragas_per_question.csv` | RAGAS 문항별 결과 |
| `run_config.json` | 실행 설정 기록 |

## 코드 수정이 단순 수정이 아닌 이유

이번 수정은 기존 답변 문장을 조금 바꾼 수준이 아닙니다. generation 로직의 책임 분리를 바꿨습니다.

| 이전 문제 | 수정 방향 |
|---|---|
| LLM이 긴 citation/evidence까지 직접 생성해서 JSON이 잘림 | LLM은 짧은 답변만 생성, citation은 코드가 붙임 |
| raw text에는 답이 있으나 final answer가 빈 값 | invalid JSON 복구 및 `_recovered_answer` 기록 |
| 복합 질문에서 일부 의도만 답변 | `intent_slots`, `intent_plan`으로 하위 요청 분리 |
| 예산 차액/합계 계산을 LLM에 의존 | `computed_values` deterministic layer에서 계산 |
| 다른 문서의 유사 예산을 가져오는 위험 | `target_slots`, `answer_policy`, target citation 검증 추가 |
| 검수 파일이 raw text 중심 | raw -> parsed -> final answer를 나란히 보는 HTML 생성 |

## 주요 진단 필드

`generated_answers.jsonl`과 review 파일에서 아래 필드를 보면 현재 답변이 왜 그런 상태인지 확인할 수 있습니다.

| 필드 | 의미 |
|---|---|
| `_valid_json` | LLM output이 정상 JSON이었는지 |
| `_recovered_answer` | invalid JSON에서 answer를 복구했는지 |
| `_parse_error_type` | JSON 파싱 실패 유형 |
| `_citation_valid` | citation 구조가 유효한지 |
| `_numeric_grounded` | 답변 숫자가 context 안에서 확인되는지 |
| `_source_numeric_grounded` | source fact 기준 숫자 근거가 확인되는지 |
| `_derived_numeric_valid` | 계산형 답변이 deterministic 계산값과 맞는지 |
| `_failure_tags` | 자동 진단 태그 목록 |
| `_missing_intents` | 복합 질문에서 누락된 하위 의도 |
| `target_slots` | 질문에서 추출한 target 문서/사업 후보와 매칭 결과 |
| `intent_plan` | 질문을 어떻게 하위 의도로 나눴는지 |
| `computed_values` | 코드가 계산한 차액/합계/비율 결과 |

## 현재 남은 한계

아직 완성 단계는 아닙니다.

1. `source_numeric_missing`이 여전히 많습니다. target 문서 안에 숫자가 있어도 `fact_candidates`로 확정하지 못하는 경우가 있습니다.
2. `전체 배정액`, `사업예산`, `추정가격`, `기초금액`, `지급조건` 같은 금액 타입 구분이 더 필요합니다.
3. 예산과 요약, 예산과 비교처럼 한 질문 안에 여러 의도가 섞이면 일부 intent가 얕게 처리될 수 있습니다.
4. citation이 target 문서와 어긋나는 경우가 아직 남아 있습니다.
5. 현재 기본 모드는 `source_store=False`라 긴 원문 근거 확장은 제한적입니다.

## 다음 개선 우선순위

1. budget candidate type 세분화
   - `project_budget`, `total_allocation`, `estimated_price`, `base_amount`, `payment_terms` 등을 분리

2. target-aware numeric fallback
   - `fact_candidates`에 없더라도 target 문서 text/table 안의 label+amount를 low/medium confidence 후보로 승격
   - 다른 문서 금액으로 대체하지 않음

3. intent별 context package 분리
   - `budget_sum`용 evidence와 `business_character_comparison`용 evidence를 따로 구성

4. citation reranking
   - target source_file 일치, required fact_type 일치, answer text 포함 여부 기준으로 citation 재선택

5. negative answer 상태 분리
   - 문서에 없다는 답변은 실패가 아니라 `answer_status=not_found_in_context`로 관리

## 보는 순서

공유 받은 팀원은 아래 순서로 보면 됩니다.

1. `src/generation/rfp_generation.py`
   - 실제 generation helper 코드

2. `src/generation/__init__.py`
   - 노트북에서 import하는 public API 목록

3. `docs/plans/generation_handoff_20260526.md`
   - 최신 실험 결과와 실패 사례 분석

4. 결과 폴더의 `llm_answer_review.html`
   - raw LLM text, parsed answer, final answer, GT를 사람이 비교하는 파일

핵심은 "LLM 답변이 한 번에 좋아졌다"가 아니라, "우리 JSON 구조를 generation 단계에서 사용할 수 있게 연결했고, 실패 원인을 검수 가능한 형태로 남기기 시작했다"는 점입니다.
