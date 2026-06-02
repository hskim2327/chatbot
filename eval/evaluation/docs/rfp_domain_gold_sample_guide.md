# Phase 3 RFP 도메인 정답지 해설서

## 1. 문서 목적

이 문서는 Phase 3 RFP 특화 평가 정답지인 `rfp_domain_gold_sample.jsonl`의 해설서다. JSONL 파일은 평가 코드가 읽는 파일이고, 이 해설서는 사람이 구조와 영어 필드명을 이해하기 위한 파일이다.

## 2. 최종 정답지 개요

- 정답지 파일: `eval/evaluation/data/rfp_domain_gold_sample.jsonl`
- record 수: 50
- 기반 세트: 사용자가 승인한 `hybrid_50`
- 구성: canonical 문항과 Phase 3 extension 문항이 섞여 있음
- 승인 방식: `batch_user_approval_from_hybrid_50`
- 주의: row-level 수동 검수가 아니라 batch approval이므로 `gold_generation_warnings`를 반드시 확인해야 함
- 사람용 파일: `rfp_domain_gold_sample.xlsx`, `rfp_domain_gold_sample_readable.csv`

## 3. 한눈에 보는 평가 항목

| 평가 항목 | 무엇을 보는지 | gold block | 주요 값 | 주의할 점 |
|---|---|---|---|---|
| 예산/금액 평가 | 금액, 합산, 예산 유형 | `budget_gold` | `amount_krw`, `total_krw`, `budget_source_type` | `threshold_budget`, `payment_terms`를 사업금액으로 오인하지 않음 |
| 여러 문서 비교 평가 | 여러 문서를 모두 다루는지 | `multi_doc_comparison_gold` | `compared_docs`, `required_comparison_axes` | 복잡한 의미 품질은 Phase 4에서 보조 평가 |
| 필수 정보 평가 | 발주기관, 사업명, 사업기간, 주요요구사항 | `required_field_gold` | `fields`, `match_type`, `expected_keywords` | 주요요구사항은 checklist/keyword 중심 |
| 제출서류/입찰자격/마감일 평가 | 제출서류, 자격요건, 날짜 | `submission_eligibility_deadline_gold` | `submission_documents`, `eligibility_terms`, `deadline` | 불완전 날짜는 warning 확인 |
| 문서에 없는 질문 대응 평가 | 확인 불가 응답 여부 | `unanswerable_gold` | `allowed_refusal_phrases`, `forbidden_claim_types` | 문서 밖 단정은 금지 |
| 오타/구어체 견고성 평가 | 같은 정답 문서와 핵심 필드 유지 | `robust_query_gold` | `expected_same_source_docs`, `expected_same_key_fields` | 원 질문 id가 없을 수 있으므로 warning 확인 |

## 4. 영어 필드명 한글 해설표

| 필드명 | 한국어 의미 |
|---|---|
| `id` | 문항 식별자 |
| `source_set` | canonical 문항인지 Phase 3 extension 문항인지 |
| `question` | 평가 질문 |
| `task_family` | Phase 3 평가 유형 |
| `secondary_task_families` | 보조 성격의 평가 유형 |
| `question_type` | 기존 eval type 또는 extension type |
| `difficulty` | 난이도 |
| `human_verified` | 사람 승인 여부 |
| `review_status` | 검수 상태 |
| `final_use_decision` | 최종 사용 결정 |
| `verification_method` | 승인 방식 |
| `reviewer` | 검수자 식별자 |
| `review_notes` | 검수/승인 메모 |
| `source_docs` | 정답 근거 문서명 |
| `identity_gold` | 발주기관, 사업명 등 식별 정보 |
| `evidence_refs` | 짧은 근거 참조 |
| `notes` | 후보 선정 또는 생성 메모 |
| `budget_gold` | 예산/금액 평가용 gold block |
| `required_field_gold` | 필수 정보 평가용 gold block |
| `submission_eligibility_deadline_gold` | 제출서류/입찰자격/마감일 평가용 gold block |
| `unanswerable_gold` | 답변 불가 평가용 gold block |
| `multi_doc_comparison_gold` | 다중 문서 비교 평가용 gold block |
| `robust_query_gold` | 오타/구어체 견고성 평가용 gold block |
| `gold_generation_status` | gold block 생성 상태 |
| `gold_generation_warnings` | 생성 중 확인된 주의사항 |
| `can_use_for_phase3` | Phase 3 공식 평가 사용 가능 여부 |

## 5. gold block별 해설

### identity_gold

발주기관과 사업명을 담는 공통 식별 정보다. 이 값이 있다고 해서 항상 점수화되는 것은 아니며, 실제 점수화 여부는 task별 gold block에서 결정한다.

### budget_gold

사업금액, 합산금액, 예산 종류, 제외해야 할 금액 후보를 담는다. 금액은 가능한 경우 KRW 정수로 저장한다.

### required_field_gold

발주기관, 사업명, 사업기간, 주요요구사항 등 질문에서 요구한 필수 정보를 field 목록으로 담는다.

### submission_eligibility_deadline_gold

제출서류, 입찰참가자격, 제안서 제출기한 또는 입찰 마감일을 담는다. 제출서류와 자격요건은 짧은 checklist 중심이다.

### unanswerable_gold

문서에 없는 질문인지, 어떤 확인 불가 표현을 허용하는지, 어떤 단정을 금지하는지 담는다.

### multi_doc_comparison_gold

비교 대상 문서, 비교 기준, 필요한 출력 구조를 담는다.

### robust_query_gold

오타/구어체 질문이 유지해야 할 정답 문서와 핵심 필드를 담는다.

## 6. JSONL record 예시

### budget 예시

```json
{"id":"Q-BUDGET","task_family":"budget","budget_gold":{"items":[{"label":"A 사업","amount_krw":1000000000,"budget_source_type":"project_budget"}],"total_krw":1000000000,"budget_unit":"KRW"}}
```

### submission_eligibility_deadline 예시

```json
{"id":"P3-SUB-EXAMPLE","task_family":"submission_eligibility_deadline","submission_eligibility_deadline_gold":{"submission_documents":["제안서","입찰참가신청서"],"eligibility_terms":["소프트웨어사업자"],"deadline":"2024-09-11"}}
```

### unanswerable 예시

```json
{"id":"Q-UNANSWERABLE","task_family":"unanswerable","unanswerable_gold":{"is_unanswerable":true,"allowed_refusal_phrases":["확인할 수 없습니다"],"forbidden_claim_types":["낙찰업체 단정"]}}
```

## 7. 사람용 Excel/CSV 해설

- `rfp_domain_gold_sample.xlsx`는 사람이 보는 최종 정답지다.
- `rfp_domain_gold_sample_readable.csv`는 빠른 확인용 요약 정답지다.
- Excel의 `all_gold` sheet와 readable CSV는 같은 내용을 담는다.
- task별 sheet는 해당 평가 유형만 필터링해서 보여준다.
- validation sheet는 각 문항의 사용 가능 여부와 warning을 보여준다.

## 8. status와 warning 해설

| 값 | 의미 |
|---|---|
| `complete` | warning 없이 생성됨 |
| `complete_with_warnings` | 사용 가능하지만 보고서에서 주의해야 함 |
| `needs_fix` | 공식 평가 전 확인 필요 |
| `can_use_for_phase3` | Phase 3 평가 투입 가능 여부 |
| `gold_generation_warnings` | 자동 변환 중 부족하거나 불확실했던 값 |

`complete_with_warnings`는 사용할 수 있지만, 결과 해석이나 보고서 작성 시 주의해야 한다. `needs_fix` 또는 `can_use_for_phase3=false`인 문항은 공식 평가에 넣으면 안 된다.

## 9. 보안/데이터 주의사항

- 원본 RFP 전문을 JSONL/XLSX/CSV에 길게 넣지 않는다.
- evidence_refs는 source_file, chunk_id, 짧은 evidence_summary 중심이다.
- API key, 개인정보, secret 값은 포함하지 않는다.
- 이 정답지는 평가용 gold label이지 원본 RFP 대체물이 아니다.

## 10. 다음 단계

1. validation 결과와 warning 문항을 확인한다.
2. `needs_fix` 문항이 있으면 공식 평가 전 보완한다.
3. Phase 3 metric 구현 시 이 JSONL을 입력으로 사용한다.
4. Phase 4 LLM Judge에는 긴 원문이 아니라 짧은 summary만 연결한다.

## Warning resolution 필드 해설

| 필드명 | 한국어 의미 |
|---|---|
| `warning_resolution_status` | warning 처리 상태. `resolved`, `accepted_warning`, `unresolved_needs_fix` 중 하나 |
| `warning_resolution_notes` | warning을 어떻게 처리했는지에 대한 짧은 설명 |

`resolved`는 근거 보완, 질문 rewrite, noisy 값 정리 등으로 warning이 실제로 해결된 상태다. `accepted_warning`은 warning이 남아 있지만 Phase 3 정답지 사용에는 문제가 없다고 판단한 상태다. 예를 들어 robust 원 질문 id가 없어도 `expected_same_source_docs`와 `expected_same_key_fields`가 충분하면 accepted_warning으로 둘 수 있다.

`unresolved_needs_fix`는 공식 평가 전에 반드시 사람이 고쳐야 하는 상태이며, 이 경우 `can_use_for_phase3=false`로 처리해야 한다.


## Phase 3 metric 구현에서 사용하는 방식

`rfp_domain_gold_sample.jsonl`은 Phase 3 도메인 평가의 기준 파일이다. 평가 코드는 `task_family`에 따라 서로 다른 gold block을 읽고, predictions JSONL의 `answer`와 일부 `retrieved_contexts`를 비교한다.

| task_family | 사용하는 gold block | 연결 metric |
|---|---|---|
| `budget` | `budget_gold` | `budget_numeric_accuracy` |
| `required_fields` | `required_field_gold` | `required_field_accuracy` |
| `submission_eligibility_deadline` | `submission_eligibility_deadline_gold` | `required_field_accuracy` |
| `unanswerable` | `unanswerable_gold` | `unanswerable_refusal_accuracy` |
| `multi_doc_comparison` | `multi_doc_comparison_gold` | `multi_doc_structure_score` |
| `robust_query_type_e` | `robust_query_gold` | `robust_query_consistency_score` |

`accepted_warning`은 평가 제외 조건이 아니다. 예를 들어 관련 원 질문 id가 없더라도 `expected_same_source_docs`와 `expected_same_key_fields`가 있으면 robust 평가를 수행할 수 있다. 다만 결과 해석 시 주의가 필요하므로 Phase 3 결과 파일의 `warning_resolution_status`와 `warning` 컬럼에 남긴다.

`can_use_for_phase3=false`인 record는 공식 Phase 3 평가에서 제외한다. 현재 최종 gold set에는 해당 문항이 없지만, 평가 코드는 향후 보완 가능성을 고려해 제외 로직을 유지한다.

## metric guide와 Phase 4 연결

이 문서는 `rfp_domain_gold_sample.jsonl`의 구조를 설명하는 정답지 해설서다. 점수가 실제로 어떻게 계산되는지는 `eval/evaluation/docs/phase3_domain_metric_guide.md`를 참고한다.

Phase 4 LLM Judge는 이 gold sample을 대체하지 않는다. Phase 4에서는 원본 RFP 전문을 보내지 않고, `domain_gold_summary`와 짧은 evidence summary만 사용해 종합 품질을 보조 평가한다. Phase 4 prompt에는 Phase 1/2/3 점수를 넣지 않는다.
## Phase 4 LLM Judge에서의 사용 관계

이 문서는 Phase 3 정답지 구조를 설명하는 해설서다. Phase 4 LLM Judge의 기본 모드는 `evidence_only`이므로 이 gold sample을 기본 Judge prompt에 넣지 않는다.

Phase 4 기본 입력에는 `question`, `rag_answer`, `source_docs`, `retrieved_evidence_summaries`만 들어간다. `domain_gold_summary`와 `ground_truth_answer_summary`는 기본 입력에서 제외한다. 이 정책은 Judge가 Phase 3 정답지를 따라가며 점수를 주는 편향을 줄이기 위한 것이다.

`gold_guided`는 선택 모드다. Phase 3 gold와 Judge 결과를 비교하거나 Judge 안정성을 분석해야 할 때만 사용하며, `evidence_only` 결과와 분리해서 기록한다. 따라서 이 정답지는 Phase 4를 대체하거나 직접 채점 기준으로 들어가는 파일이 아니라, 선택적 분석 모드에서 짧은 요약으로만 참조할 수 있는 자료다.
