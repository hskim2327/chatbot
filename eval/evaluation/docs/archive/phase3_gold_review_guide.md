# Phase 3 RFP 특화 Gold Label 검수 가이드

## 1. 문서 목적

이 문서는 Phase 3 RFP 특화 평가를 위한 gold label 검수 가이드다. 코드 구현 문서가 아니라, 사람이 `rfp_domain_gold_review.xlsx`를 검수할 때 따라야 하는 작업 기준을 정리한다.

Phase 3는 기존 500문항 전체를 바로 평가하지 않는다. 먼저 50문항 pilot gold set을 만들고, 사람이 검수한 문항만 공식 Phase 3 평가에 사용한다.

검수의 핵심 원칙은 다음이다.

- 기존 eval 500문항은 후보 질문 풀이다.
- `new_data`의 `metadata_light_690.xlsx`와 `chunks_v2_690.jsonl`은 정답 후보 자료다.
- `fact_candidates`와 `final_*` 컬럼은 검수 전에는 정답이 아니다.
- 공식 정답으로 쓰려면 `human_verified=true`와 `review_status=verified`가 모두 필요하다.

## 2. 왜 기존 500문항을 보는가

기존 canonical 500문항은 새 정답지가 아니라 후보 질문 풀이다. 새로 만드는 것은 질문 자체가 아니라 RFP 특화 구조화 gold label이다.

기존 500문항에는 이미 다음 정보가 있다.

- `id`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`

이 정보를 재사용하면 Phase 1 검색 성능, Phase 2 RAGAS 생성 품질, Phase 3 RFP 특화 평가, Phase 4 LLM Judge 결과를 같은 `id`로 연결할 수 있다.

반대로 완전히 새 질문을 만들면 `id`, `question`, `ground_truth_docs`, `ground_truth_answer`, `type`, `difficulty`를 모두 새로 만들어야 하므로 작업량과 검수 비용이 커진다.

비유하면, 기존 500문항은 이미 만들어진 시험 문제지다. Phase 3 gold label은 그중 50문항에 새로 붙이는 상세 채점 기준표다.

## 3. 전체 파일 흐름

Phase 3 gold label 준비 흐름은 다음과 같다.

```text
data/eval/eval_batch_01.csv ~ eval_batch_25.csv
+ new_data/metadata_light_690.xlsx
+ new_data/chunks_v2_690.jsonl
↓
eval/evaluation/data/rfp_domain_gold_candidates.csv
↓
eval/evaluation/data/rfp_domain_gold_review.xlsx
↓
eval/evaluation/data/rfp_domain_gold_sample.jsonl
↓
Phase 3 평가
```

각 파일의 역할은 다음과 같다.

| 파일 | 역할 | 정답 여부 |
|---|---|---|
| `rfp_domain_gold_candidates.csv` | 자동 후보 추출 결과 | 아직 정답 아님 |
| `rfp_domain_gold_review.xlsx` | 사람이 검수하는 작업표 | 검수 중인 정답 후보 |
| `rfp_domain_gold_sample.jsonl` | 실제 평가 코드가 읽는 최종 정답지 | 공식 평가 정답 |

`rfp_domain_gold_sample.jsonl`에는 `human_verified=true`, `review_status=verified`인 문항만 들어간다.

## 4. 50문항 pilot gold set 구성

Phase 3 pilot gold set은 50문항으로 고정한다.

| task_family | 문항 수 | 목적 |
|---|---:|---|
| `budget` | 12 | 단일/합산 예산, 단위 변환, 금액 혼동 평가 |
| `multi_doc_comparison` | 10 | 여러 문서 비교, 공통점/차이점 구조 평가 |
| `required_fields` | 10 | 발주기관, 사업명, 사업기간, 주요요구사항 등 필수 필드 평가 |
| `submission_eligibility_deadline` | 8 | 제출서류, 입찰자격, 마감일 평가 |
| `unanswerable` | 7 | 문서에 없는 질문 대응 평가 |
| `robust_query_type_e` | 3 | 오타/구어체 견고성 평가 |

합계는 50문항이다. 50문항 모두 사람이 검수해야 하며, 검수되지 않은 문항은 공식 Phase 3 평가에 사용하지 않는다.

## 5. 검수용 Excel sheet 구조

`eval/evaluation/data/rfp_domain_gold_review.xlsx`는 multi-sheet 구조로 설계한다. 모든 task_family를 한 시트에 넣으면 컬럼이 너무 많아져 검수자가 혼동할 수 있기 때문이다.

필수 sheet는 다음과 같다.

- `README`
- `candidates_all`
- `budget_review`
- `multi_doc_comparison_review`
- `required_fields_review`
- `submission_eligibility_deadline_review`
- `unanswerable_review`
- `robust_query_review`

### README

목적:

- 검수 원칙, `review_status` 의미, `human_verified` 기준, 금지사항을 설명한다.

주요 내용:

- `fact_candidates`는 정답이 아니라 후보임
- `final_*` 컬럼도 자동 추출값이므로 검수 필요
- 원본 RFP 본문을 길게 복사하지 않음
- 불확실하면 `verified`가 아니라 `needs_review` 또는 `needs_fix`로 둠

### candidates_all

목적:

- 자동 후보 추출 전체 목록을 보여준다.
- 사람이 직접 정답을 확정하는 시트가 아니라 전체 후보 탐색용이다.

주요 입력 컬럼:

- `id`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`
- `num_ground_truth_docs`
- `task_family_candidate`
- `candidate_source_docs`
- `candidate_agencies`
- `candidate_project_names`
- `candidate_budget_values`
- `candidate_submission_documents`
- `candidate_eligibility_terms`
- `candidate_deadline`
- `candidate_fact_chunk_ids`
- `candidate_reason`
- `needs_review`

verified 처리 기준:

- 이 시트에서는 직접 `verified` 처리하지 않는다. task별 review sheet로 옮겨 검수한다.

### budget_review

목적:

- 예산/금액 질문을 검수한다.
- `project_budget`, `threshold_budget`, `base_amount`, `estimated_price`, `payment_terms` 혼동 여부를 확인한다.

주요 입력 컬럼:

- `id`
- `question`
- `ground_truth_docs`
- `candidate_budget_values`
- `candidate_fact_chunk_ids`
- `candidate_source_docs`
- `candidate_agencies`
- `candidate_project_names`

reviewer가 확정해야 하는 컬럼:

- `reviewer_confirmed_source_docs`
- `reviewer_confirmed_agencies`
- `reviewer_confirmed_project_names`
- `reviewer_confirmed_budget_items`
- `reviewer_confirmed_total_krw`
- `budget_source_type`
- `excluded_budget_candidates`
- `budget_exception_approved`
- `budget_exception_reason`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- `amount_krw`가 KRW 기준으로 확정됨
- `budget_source_type`이 명확함
- 제외해야 할 금액 후보가 있으면 `excluded_budget_candidates`에 기록됨
- 예외 승인 시 `budget_exception_reason`이 있음

rejected 또는 needs_fix 기준:

- 금액 후보가 불명확함
- `budget_source_type=unknown`
- 사업금액과 자격기준금액을 구분할 수 없음
- 근거가 길거나 원문 전문이 포함됨

### multi_doc_comparison_review

목적:

- 다중 문서 비교 질문을 검수한다.
- 비교 대상 문서, 비교 축, 요구 출력 구조를 확정한다.

주요 입력 컬럼:

- `id`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`
- `num_ground_truth_docs`
- `candidate_source_docs`

reviewer가 확정해야 하는 컬럼:

- `compared_docs`
- `required_doc_coverage`
- `required_comparison_axes`
- `required_output_structure`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- 비교 대상 문서 수가 명확함
- 비교 축이 질문 의도와 맞음
- 공통점, 차이점, 문서별 요약 등 요구 출력 구조가 명확함

rejected 또는 needs_fix 기준:

- 비교 대상 문서가 불명확함
- 질문이 실제로 비교 과제가 아님
- 비교 축을 구조화할 수 없음

### required_fields_review

목적:

- 발주기관, 사업명, 사업기간, 주요요구사항 등 필수 필드를 검수한다.

주요 입력 컬럼:

- `id`
- `question`
- `ground_truth_docs`
- `candidate_agencies`
- `candidate_project_names`
- `candidate_fact_chunk_ids`

reviewer가 확정해야 하는 컬럼:

- `reviewer_confirmed_required_fields`
- `field_name`
- `match_type`
- `expected_value`
- `expected_values`
- `expected_keywords`
- `min_match_count`
- `required`
- `weight`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- 각 field의 `match_type`이 정해짐
- `expected_value`, `expected_values`, `expected_keywords` 중 필요한 값이 채워짐
- 주요요구사항은 자유 의미평가가 아니라 `keyword_coverage` 또는 `checklist_coverage`로 표현됨

rejected 또는 needs_fix 기준:

- 질문이 요구하는 필드가 불명확함
- expected 값이 원문 전체처럼 너무 김
- 의미평가 없이는 채점할 수 없음

### submission_eligibility_deadline_review

목적:

- 제출서류, 입찰자격, 마감일을 검수한다.

주요 입력 컬럼:

- `id`
- `question`
- `ground_truth_docs`
- `candidate_submission_documents`
- `candidate_eligibility_terms`
- `candidate_deadline`
- `candidate_fact_chunk_ids`

reviewer가 확정해야 하는 컬럼:

- `reviewer_confirmed_submission_documents`
- `reviewer_confirmed_eligibility_terms`
- `reviewer_confirmed_deadline`
- `deadline_type`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- 제출서류와 입찰자격은 긴 원문이 아니라 짧은 checklist로 정리됨
- 마감일이 있으면 날짜 표현이 검수됨
- 마감일이 문서에 없으면 없는 것으로 명확히 표시됨

rejected 또는 needs_fix 기준:

- 제출서류/자격요건이 너무 길어 checklist로 축약되지 않음
- 마감일 후보가 서로 충돌함
- 근거가 불명확함

### unanswerable_review

목적:

- 문서에 없는 질문인지 확인한다.
- 허용 refusal 표현과 금지 단정 유형을 검수한다.

주요 입력 컬럼:

- `id`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`
- `candidate_reason`

reviewer가 확정해야 하는 컬럼:

- `is_unanswerable`
- `allowed_refusal_phrases`
- `forbidden_claim_types`
- `forbidden_hallucination_patterns`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- 실제 문서 범위에서 답변 불가능한 질문임을 확인함
- 답변 불가 표현과 금지 단정 유형이 정리됨

rejected 또는 needs_fix 기준:

- 문서 안에 답이 있을 가능성이 있음
- 질문 의도가 모호함
- 금지 단정 유형이 정리되지 않음

### robust_query_review

목적:

- 오타/구어체 질문이 원 질문과 같은 정답 문서와 핵심 필드를 유지해야 하는지 검수한다.

주요 입력 컬럼:

- `id`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`
- `candidate_source_docs`

reviewer가 확정해야 하는 컬럼:

- `canonical_question_id`
- `related_original_id`
- `expected_same_source_docs`
- `expected_same_key_fields`
- `evidence_refs`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

verified 처리 기준:

- 오타/구어체 질문이 어떤 원 질문과 대응되는지 명확함
- 같은 정답 문서 또는 핵심 필드를 유지해야 하는지 확인됨

rejected 또는 needs_fix 기준:

- 대응되는 원 질문을 찾을 수 없음
- 오타/구어체가 아니라 별도 의도의 질문임
- 유지해야 할 핵심 필드가 불명확함

## 6. 공통 검수 규칙

모든 sheet에서 다음 규칙을 따른다.

- `fact_candidates`는 정답이 아니라 후보이다.
- `metadata_light_690.xlsx`의 `final_*` 컬럼도 자동 추출값이므로 검수 전에는 정답이 아니다.
- `human_verified=true`와 `review_status=verified`가 모두 만족되어야 공식 Phase 3 정답으로 사용한다.
- `reviewer`에는 개인 실명 대신 `team_reviewer_1`, `pair_reviewed`, `mentor_reviewed` 같은 역할 기반 식별자를 쓴다.
- 원본 RFP 본문을 길게 복사하지 않는다.
- evidence는 `source_file`, `chunk_id`, 짧은 `evidence_summary`로 제한한다.
- 불확실하면 `verified`로 확정하지 말고 `needs_fix` 또는 `needs_review`로 둔다.

## 7. review_status 기준

| review_status | 의미 | 공식 평가 사용 여부 |
|---|---|---|
| `needs_review` | 아직 검수 전 | 사용 불가 |
| `verified` | 사람이 검수 완료 | `human_verified=true`이면 사용 가능 |
| `rejected` | Phase 3 pilot에 부적합 | 사용 불가 |
| `needs_fix` | 후보는 적절하지만 값 수정, 근거 확인, task_family 재분류 필요 | 사용 불가 |

`rejected` 예시는 질문 의도가 불명확하거나 gold label 작성이 불가능한 경우다. `needs_fix` 예시는 후보 문항은 적절하지만 금액, 근거, task_family, checklist 값이 더 확인되어야 하는 경우다.

## 8. human_verified 기준

`human_verified=true`가 되려면 다음 조건을 만족해야 한다.

- `source_docs`가 실제 `ground_truth_docs`와 일치하거나 합리적으로 매칭됨
- 필요한 gold 값이 사람 검수로 확정됨
- 예산이면 `budget_source_type`이 명확함
- 제출서류/입찰자격이면 검수된 짧은 checklist가 있음
- unanswerable이면 실제 문서 범위에서 답변 불가 여부가 확인됨
- `evidence_summary`가 짧고 충분함
- API key, 개인정보, 원문 전문이 포함되지 않음

하나라도 불확실하면 `human_verified=false`로 두고 `review_status=needs_fix` 또는 `needs_review`를 사용한다.

## 9. task_family별 검수 방법

### budget

검수할 항목:

- `source_docs`
- agency/project_name
- `amount_krw`
- `budget_source_type`
- `total_krw`
- `excluded_budget_candidates`
- 단위 변환
- `project_budget`과 `threshold_budget`, `base_amount`, `estimated_price`, `payment_terms` 혼동 여부

verified 조건:

- `amount_krw`가 KRW 기준으로 확정됨
- `budget_source_type`이 명확함
- 제외해야 할 금액 후보가 있으면 `excluded_budget_candidates`에 기록됨
- `estimated_price` 또는 `base_amount`를 예외 승인하면 `notes`에 이유가 있음

### multi_doc_comparison

검수할 항목:

- `compared_docs`
- `required_doc_coverage`
- `required_comparison_axes`
- `required_output_structure`

verified 조건:

- 비교 대상 문서 수가 명확함
- 비교 축이 질문 의도와 맞음
- 공통점, 차이점, 문서별 요약 등 요구 출력 구조가 명확함

### required_fields

검수할 항목:

- 발주기관
- 사업명
- 사업기간
- 주요요구사항
- 기타 질문에서 요구한 필수 필드

verified 조건:

- 각 field의 `match_type`이 정해짐
- `expected_value`, `expected_values`, `expected_keywords` 중 필요한 값이 채워짐
- 주요요구사항은 자유 의미평가가 아니라 `keyword_coverage` 또는 `checklist_coverage`로 표현됨

### submission_eligibility_deadline

검수할 항목:

- 제출서류
- 입찰자격
- 마감일
- `deadline_type`

verified 조건:

- 제출서류와 입찰자격은 긴 원문이 아니라 짧은 checklist로 정리됨
- 마감일이 있으면 날짜 표현이 검수됨
- 마감일이 문서에 없으면 없는 것으로 명확히 표시됨

### unanswerable

검수할 항목:

- `is_unanswerable`
- `allowed_refusal_phrases`
- `forbidden_claim_types`
- `forbidden_hallucination_patterns`

verified 조건:

- 실제 문서 범위에서 답변 불가능한 질문임을 확인함
- 답변 불가 표현과 금지 단정 유형이 정리됨

### robust_query_type_e

검수할 항목:

- `canonical_question_id` 또는 `related_original_id`
- `expected_same_source_docs`
- `expected_same_key_fields`

verified 조건:

- 오타/구어체 질문이 어떤 원 질문과 대응되는지 명확함
- 같은 정답 문서 또는 핵심 필드를 유지해야 하는지 확인됨

## 10. budget_source_type 판정 규칙

| budget_source_type | 기본 사업금액 답변 사용 | 예외 사용 가능 여부 | 설명 |
|---|---|---|---|
| `project_budget` | 가능 | 기본값 | 사업금액/예산으로 검수된 값 |
| `estimated_price` | 원칙적으로 보조 | 사람 검수 시 가능 | `project_budget` 부재 시 기준 금액으로 승인 가능 |
| `base_amount` | 원칙적으로 보조 | 사람 검수 시 가능 | `project_budget` 부재 시 기준 금액으로 승인 가능 |
| `threshold_budget` | 불가 | 자격요건 질문에서만 가능 | 입찰참가자격 기준 금액일 수 있음 |
| `payment_terms` | 불가 | 지급조건 질문에서만 가능 | 사업금액이 아니라 지급 조건 |
| `unknown` | 불가 | 검수 필요 | 공식 평가 제외 또는 `needs_fix` |

추가 규칙은 다음과 같다.

- 사업금액 질문에서 `threshold_budget`을 답하면 치명 오류 후보이다.
- `payment_terms`는 지급조건 질문에서는 유용하지만 사업금액으로 쓰면 안 된다.
- `estimated_price` 또는 `base_amount`를 허용하려면 반드시 `notes`에 이유를 남긴다.
- `project_budget`이 문서에 없고 사람이 `estimated_price` 또는 `base_amount`를 해당 질문의 기준 금액으로 검수한 경우에만 예외적으로 허용한다.

## 11. identity_gold 점수화 기준

`identity_gold`는 발주기관과 사업명을 담는 공통 식별 정보다.

중요한 기준은 다음과 같다.

- `identity_gold`에 값이 있다고 해서 항상 점수에 들어가는 것은 아니다.
- 점수에 포함하려면 `required_field_gold.fields`에 `field_name=agency` 또는 `field_name=project_name`으로 명시해야 한다.
- 질문이 이미 특정 기관/사업명을 명시하고 있고 답변이 그 맥락을 유지한다면, `identity_gold`는 참고 정보로만 사용할 수 있다.
- 질문이 "각 사업별로 정리하라" 또는 "세 기관을 비교하라"라고 요구하면 agency/project_name을 required field로 넣는 것을 권장한다.

예시는 다음과 같다.

```json
{
  "identity_gold": {
    "agencies": ["기관 A"],
    "project_names": ["사업 A"]
  },
  "required_field_gold": {
    "fields": [
      {
        "field_name": "agency",
        "match_type": "exact_or_alias",
        "expected_values": ["기관 A"],
        "required": true,
        "weight": 1.0
      }
    ]
  }
}
```

위 예시에서는 agency가 `required_field_gold`에 들어 있으므로 점수화한다. 반대로 `identity_gold`에만 있으면 문서/사업 식별 참고 정보로만 사용한다.

## 12. multi_doc_structure_score와 robust_query_consistency_score

Phase 3 v0 공식 대표 지표는 다음 세 개다.

- `required_field_accuracy`
- `budget_numeric_accuracy`
- `unanswerable_refusal_accuracy`

`multi_doc_comparison`과 `robust_query_type_e`는 v0에서 별도 보조 분석 metric으로 둔다.

### multi_doc_structure_score

목적:

- 다중 문서 비교 질문에서 모든 문서를 다뤘는지, 비교 축과 출력 구조를 지켰는지 본다.

평가 후보:

- `doc_coverage_score`
- `comparison_axis_score`
- `output_structure_score`

초기에는 공식 Phase 3 평균에 넣지 않고 보조 컬럼으로 기록하는 것을 권장한다.

### robust_query_consistency_score

목적:

- 오타/구어체 질문에서도 원 질문과 같은 정답 문서와 핵심 필드를 유지하는지 본다.

평가 후보:

- `same_source_doc_match`
- `same_key_field_match`

초기에는 공식 Phase 3 평균에 넣지 않고 보조 컬럼으로 기록하는 것을 권장한다.

## 13. JSONL 변환 규칙

`rfp_domain_gold_review.xlsx`에서 `rfp_domain_gold_sample.jsonl`로 변환할 때의 규칙은 다음과 같다.

포함 조건:

- `human_verified == true`
- `review_status == verified`

제외 조건:

- `review_status=needs_review`
- `review_status=needs_fix`
- `review_status=rejected`
- `human_verified != true`
- `source_docs` 불명확
- `budget_source_type=unknown`
- `evidence_summary`가 과도하게 김
- 원본 본문 과다 포함

변환 규칙:

- 각 sheet에서 `task_family`별 record 생성
- 공통 필드 생성
- `task_family`에 맞는 gold block만 생성
- 빈 block은 생성하지 않음
- `source_file`, `chunk_id`, `evidence_summary`만 근거로 포함
- 원문 전문, 긴 table, source_store 전체는 포함하지 않음

## 14. Phase 4 domain_gold_summary 생성 규칙

Phase 4에서 사용할 `domain_gold_summary`는 사람이 새로 쓰는 것이 아니라 Phase 3 gold JSONL에서 자동 생성하는 것으로 설계한다.

규칙:

- 최대 500자
- 원본 RFP 본문 포함 금지
- `budget_gold`가 있으면 budget items와 `total_krw`만 요약
- `required_field_gold`가 있으면 `required=true` 필드만 요약
- `unanswerable_gold`가 있으면 `is_unanswerable`과 `forbidden_claim_types`만 요약
- `multi_doc_comparison_gold`가 있으면 `compared_docs`, `required_comparison_axes`, `required_output_structure`만 요약
- `robust_query_gold`가 있으면 `expected_same_source_docs`와 `expected_same_key_fields`만 요약

예시는 다음과 같다.

```text
예산 기준: A 사업 project_budget=1,000,000,000 KRW, total_krw=1,000,000,000.
필수 필드: agency, project_name, project_duration.
비교 기준: compared_docs 2개, 비교 축은 예산/주요요구사항, 출력 구조는 공통점/차이점.
```

이 예시는 요약 형식만 보여준다. 실제 문서에는 원본 RFP 본문이나 긴 evidence를 넣지 않는다.

## 15. 보안 및 데이터 주의사항

검수 과정에서 다음 사항을 반드시 지킨다.

- 원본 RFP 전문을 검수 파일, JSONL, 문서, 로그에 길게 복사하지 않는다.
- API key, SSH key, 개인정보는 절대 기록하지 않는다.
- source_store 전체를 외부 API나 로그에 넣지 않는다.
- evidence_summary는 짧게 쓴다.
- 검수 과정에서 불확실한 값은 `verified` 처리하지 않는다.
- 외부 API를 사용하는 Phase 4 실행 전에는 팀/멘토 승인을 받아야 한다.
