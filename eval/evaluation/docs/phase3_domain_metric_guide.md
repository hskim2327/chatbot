# Phase 3 RFP 도메인 평가 점수 해설서

## 1. 문서 목적

이 문서는 Phase 3 RFP 도메인 평가 점수가 어떻게 계산되고 어떻게 해석되는지 설명한다. 코드 구현 상세 문서가 아니라, 팀원이 결과 CSV와 보고서를 읽을 때 어떤 의미로 받아들여야 하는지 정리한 기준 문서다.

현재 실제 RAG pipeline output인 production predictions JSONL은 아직 준비되지 않았다. 따라서 현재 단계에서는 synthetic/mock predictions로 평가 로직을 검증하고, 실제 end-to-end 평가는 RAG pipeline 결합 이후 수행한다.

## 2. Phase 1/2/3 차이

| 단계 | 평가 질문 | 주요 입력 | 결과 의미 |
|---|---|---|---|
| Phase 1 | 정답 문서를 잘 검색했는가 | eval CSV, predictions의 `retrieved_contexts` | document-level retrieval 성능 |
| Phase 2 | 생성 답변이 RAGAS 기준으로 좋은가 | RAGAS dataset | faithfulness, relevancy, context 품질 |
| Phase 3 | RFP 실무 정답 요소를 답변에 반영했는가 | predictions, `rfp_domain_gold_sample.jsonl` | 예산, 필수 정보, 제출/자격/마감, 답변불가 등 도메인 품질 |

Phase 3는 Phase 1/2를 대체하지 않는다. 검색이 맞았는지, RAGAS 점수가 어떤지와 별개로 RFP 실무에서 중요한 필드가 답변에 들어갔는지를 deterministic rule로 본다.

## 3. Phase 3 입력 구조

Phase 3는 두 파일을 `id` 기준으로 매칭한다.

### predictions JSONL

필수 필드:

- `id`
- `question`
- `answer`
- `retrieved_contexts`

`answer`는 대부분의 도메인 metric 계산에 직접 사용된다. `retrieved_contexts`는 다중 문서 비교와 robust query 평가에서 문서 coverage를 확인할 때 보조로 사용된다.

### rfp_domain_gold_sample.jsonl

주요 필드:

- `id`
- `task_family`
- task별 gold block
- `can_use_for_phase3`
- `warning_resolution_status`

`can_use_for_phase3=false`인 문항은 평가에서 제외된다. 현재 최종 gold set에는 해당 문항이 없다. `warning_resolution_status=accepted_warning`인 문항은 평가에서 제외하지 않고 해석 주의 플래그로 남긴다.

## 4. Phase 3 평가 항목 6개

| task_family | 평가 내용 | 사용하는 gold block | 대표 metric | 점수가 낮은 대표 원인 |
|---|---|---|---|---|
| `budget` | 예산/금액/합산 금액이 맞는지 | `budget_gold` | `budget_numeric_accuracy` | 금액 누락, 단위 변환 오류, threshold/payment 금액 혼동 |
| `multi_doc_comparison` | 여러 문서를 모두 다루고 비교 구조를 지켰는지 | `multi_doc_comparison_gold` | `multi_doc_structure_score` | 일부 문서만 언급, 비교축 누락, 공통점/차이점 구조 없음 |
| `required_fields` | 발주기관, 사업명, 기간, 주요요구사항 등 필수 정보 포함 여부 | `required_field_gold` | `required_field_accuracy` | 필드 누락, 키워드/checklist 부족 |
| `submission_eligibility_deadline` | 제출서류, 입찰자격, 마감일 포함 여부 | `submission_eligibility_deadline_gold` | `required_field_accuracy` | 제출서류/자격 checklist 누락, 날짜 불일치 |
| `unanswerable` | 문서에 없는 질문에 확인 불가로 답했는지 | `unanswerable_gold` | `unanswerable_refusal_accuracy` | 낙찰업체/계약결과 등 문서 밖 정보를 단정 |
| `robust_query_type_e` | 오타/구어체 질문에서도 같은 문서와 핵심 필드를 유지하는지 | `robust_query_gold` | `robust_query_consistency_score` | 정답 문서 이탈, 핵심 필드 누락 |

## 5. metric별 계산 방식

### budget_numeric_accuracy

답변에서 금액 표현을 추출하고 `원`, `천원`, `백만원`, `억원` 등을 KRW 정수로 정규화한다. 이후 `budget_gold.items[*].amount_krw`와 `budget_gold.total_krw`를 비교한다.

`tolerance_krw`와 `tolerance_ratio`가 있으면 허용 오차를 반영한다. `threshold_budget`, `payment_terms`처럼 사업금액이 아닌 값을 사업금액처럼 답하면 감점 또는 warning 대상이다.

### required_field_accuracy

`required_fields`와 `submission_eligibility_deadline` 계열에 사용된다. `required_field_gold.fields` 또는 `submission_eligibility_deadline_gold`의 checklist를 기준으로 답변에 핵심 항목이 있는지 본다.

지원 rule:

- `exact`
- `exact_or_alias`
- `numeric_krw`
- `date`
- `keyword_coverage`
- `checklist_coverage`

필드별 weight가 있으면 `matched_weight / total_weight`로 계산한다.

### unanswerable_refusal_accuracy

문서에 없는 질문에서 답변이 지어내지 않고 확인 불가로 응답했는지 본다. `allowed_refusal_phrases`가 있으면 긍정 평가하고, `forbidden_claim_types`나 `forbidden_hallucination_patterns`에 해당하는 단정이 있으면 감점한다.

확인 불가라고 말하면서 추측을 덧붙이는 경우는 부분 감점될 수 있다.

### multi_doc_structure_score

다중 문서 비교 질문에서 다음 세 값을 계산해 평균한다.

- `doc_coverage_score`: 비교 대상 문서를 모두 다뤘는지
- `comparison_axis_score`: 예산, 사업목표, 주요요구사항 등 비교축을 반영했는지
- `output_structure_score`: 문서별 요약, 공통점, 차이점 같은 출력 구조를 지켰는지

복잡한 의미적 비교 품질은 Phase 4에서 보완한다.

### robust_query_consistency_score

오타/구어체 질문에서도 같은 정답 문서와 핵심 필드를 유지하는지 본다. `expected_same_source_docs`는 `retrieved_contexts`의 top-k unique documents와 비교하고, `expected_same_key_fields`는 답변의 키워드 포함 여부로 확인한다.

`accepted_warning` 문항도 평가에서 제외하지 않는다. 예를 들어 Q039는 관련 원 질문 id가 없어도 expected source docs와 key fields가 있어 robust 평가가 가능하다.

## 6. phase3_task_score

각 문항의 대표 점수는 `task_family`별 대표 metric을 사용한다.

| task_family | phase3_task_score |
|---|---|
| `budget` | `budget_numeric_accuracy` |
| `required_fields` | `required_field_accuracy` |
| `submission_eligibility_deadline` | `required_field_accuracy` |
| `unanswerable` | `unanswerable_refusal_accuracy` |
| `multi_doc_comparison` | `multi_doc_structure_score` |
| `robust_query_type_e` | `robust_query_consistency_score` |

## 7. 결과 파일 해설

- `phase3_domain_results.csv`: 문항별 Phase 3 metric 결과
- `phase3_domain_results.json`: 같은 결과의 JSON 버전
- `phase3_domain_summary.md`: 전체 평균, 평가/제외 문항 수, warning 요약
- `phase3_domain_by_task.csv`: task_family별 평균과 실패 수
- `phase3_domain_failure_cases.csv`: 오류 또는 낮은 점수 문항 확인용
- `experiment_logs/phase3_domain_experiments.csv`: 실험별 Phase 3 결과 누적 로그

## 8. 점수 해석 기준

점수는 0~1 사이 값이다.

| 점수 구간 | 권장 해석 |
|---|---|
| 0.85~1.00 | 매우 좋음 |
| 0.70~0.85 | 실사용 가능하지만 개선 여지 있음 |
| 0.50~0.70 | 부분적으로 동작하지만 불안정 |
| 0.30~0.50 | 도메인 질의 대응이 약함 |
| 0.00~0.30 | 실패에 가까움 |

이 기준은 절대 기준이 아니라 실험 간 비교 기준이다. 특히 synthetic/mock predictions 결과는 실제 성능으로 해석하면 안 된다.

## 9. warning 처리 방식

- `can_use_for_phase3=false`: 평가 제외
- `accepted_warning`: 평가 제외하지 않음
- `accepted_warning`: 결과 해석 시 주의 플래그
- 현재 최종 gold set에는 `can_use_for_phase3=false` 문항이 없음
- Q039는 `accepted_warning`이지만 robust 평가 가능 문항임

## 10. 한계와 Phase 4 필요성

Phase 3는 deterministic rule 기반이라 숫자, 키워드, checklist, 거절 표현, 비교 구조를 잘 본다.

반면 다음은 한계가 있다.

- 답변의 깊은 의미 품질
- 설명의 설득력
- 복잡한 비교의 논리성
- RFP 실무 관점의 유용성
- 부분적으로 맞지만 애매한 답변의 세밀한 판단

따라서 Phase 4 LLM Judge가 필요하다. Phase 4는 Phase 3를 대체하지 않고, Phase 3가 보기 어려운 종합 품질을 보조적으로 평가한다.
## Phase 4 LLM Judge와의 관계

Phase 3는 `rfp_domain_gold_sample.jsonl`의 gold block을 사용하는 deterministic rule 기반 평가다. 예산, 필수 필드, 제출서류/입찰자격/마감일, 답변 불가, 다중 문서 구조, 오타/구어체 견고성처럼 구조화된 정답 요소를 계산 가능한 규칙으로 확인한다.

Phase 4는 Phase 3 점수를 대체하지 않는다. Phase 4는 기본적으로 gold를 보지 않는 `evidence_only` LLM Judge 평가이며, `question`, `rag_answer`, `source_docs`, `retrieved_evidence_summaries`만 사용해 실무 유용성, 근거성, 숫자/사실 정확성, 구조 명확성, 위험 통제를 종합 진단한다.

따라서 Phase 3 점수는 정답 요소 반영 여부를 보는 deterministic signal이고, Phase 4 점수는 같은 evidence 조건에서 답변이 실무적으로 얼마나 쓸 만한지 보는 보조 진단 signal이다. 두 점수는 서로 대체 관계가 아니라 함께 해석해야 한다.
