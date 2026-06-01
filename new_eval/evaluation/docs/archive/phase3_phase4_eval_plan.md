# Phase 3/4 RAG 평가 설계 문서

## 1. 목적과 범위

이 문서는 기존 RAG 평가 모듈에 Phase 3 RFP 도메인 특화 평가와 Phase 4 LLM API 기반 종합 평가를 추가하기 위한 설계 문서다. 이번 단계에서는 코드를 구현하지 않고, 현재 프로젝트 데이터와 평가 방법론을 바탕으로 구현 가능한 수준의 입력 파일, gold schema, 지표, judge prompt, 보안 정책을 정리한다.

현재 구현된 Phase 1/2 정책은 변경하지 않는다. Phase 3와 Phase 4는 기존 공식 검색/생성 평가를 대체하지 않고, RFP 실무 품질을 더 세밀하게 해석하기 위한 확장 평가다.

이 문서에서 사용하는 산출물 경로는 실제 저장소 구조 기준으로 `eval/evaluation/...`에 통일한다.

## 2. 현재 Phase 1/2와의 관계

현재 평가 모듈은 `eval/evaluation/` 아래에 있다. 실행 entrypoint는 `eval/evaluation/scripts/run_evaluation.py`이고, 패키지는 `eval/evaluation/src/rag_eval/`이다.

유지해야 하는 기존 정책은 다음과 같다.

- Phase 1은 document-level retrieval evaluation이다.
- Phase 1 공식 metric은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`만 사용한다.
- 공식 `top_k`는 5다.
- `retrieved_contexts`는 `rank` 오름차순 정렬 후 `filename` 우선, `doc_id` 보조 기준으로 top-5 unique documents를 만든다.
- `ground_truth_docs`가 비어 있으면 Phase 1 metric은 NaN으로 기록한다.
- Phase 2는 RAGAS 라이브러리와 `evaluate(dataset, metrics=[...])` 기본 evaluator 방식을 고정 사용한다.
- RAGAS에 custom llm, custom embeddings, 별도 judge backend adapter를 주입하지 않는다.
- 기본 실행은 Phase 1만 수행하고, `--enable-ragas`가 있을 때만 Phase 2를 수행한다.
- `--require-ragas`는 최종 제출용 strict mode다.
- experiment logs는 append-only다.
- API key 값과 원본 RFP 본문은 어떤 로그/문서/리포트에도 저장하지 않는다.

Phase 3와 Phase 4는 별도 입력 파일과 별도 결과 파일을 추가하는 방식으로 설계한다. 기존 Phase 1/2 결과를 계산하는 코드 경로와 공식 지표는 건드리지 않는다.

## 3. new_data 파일 분석 요약

확인한 `new_data` 주요 파일은 다음과 같다.

| 파일 | 용도 | Phase 3/4 관련성 |
|---|---|---|
| `new_data/README.md` | P4 HWPX 690 retrieval-ready corpus 설명 | corpus 사용 기준, 보안 주의사항, validation summary 확인 |
| `new_data/CHROMA_LOAD_GUIDE.md` | Chroma 적재 가이드 | `chunk_id`, `content`, `metadata` 매핑과 적재 필터 기준 확인 |
| `new_data/validation_report_v2.json` | v2 corpus 검증 결과 | corpus 품질과 fact 후보 분포 확인 |
| `new_data/metadata_light_690.xlsx` | 문서별 요약 metadata와 preview | Phase 3 후보 라벨 생성과 사람 검수 참고 자료 |
| `new_data/chunks_v2_690.jsonl` | table-aware structured retrieval index | fact 후보, answer policy, evidence 연결 정보 확인 |

`new_data/README.md`와 `CHROMA_LOAD_GUIDE.md`의 핵심 원칙은 다음과 같다.

- 기본 retrieval 실험은 `chunks_v2_690.jsonl`을 사용한다.
- Chroma 적재 시 `chunk_id`는 ids, `content`는 documents, `metadata`는 metadatas로 사용한다.
- 적재 전 `embed_enabled=true`, `chunk_type != "toc"`, 빈 content 제외 조건을 적용한다.
- `source_store_v2_690.jsonl`은 긴 원문/표 구조 근거 조회용이며 Chroma metadata에 그대로 넣지 않는다.
- 긴 원문, table 전체 JSON, OCR 전문, rows/list/dict는 Chroma metadata에 넣지 않는다.
- 원본 RFP, source_store, Chroma DB, embedding cache는 GitHub 업로드 대상이 아니다.

## 4. metadata_light_690.xlsx 분석 결과

`new_data/metadata_light_690.xlsx`는 690행, 73열이다. 문서 단위 metadata와 5,000자 preview가 포함되어 있으며, 임베딩 대상이 아니라 사람이 검토하는 참고 자료에 가깝다.

주요 컬럼 그룹은 다음과 같다.

| 구분 | 관련 컬럼 |
|---|---|
| 문서 식별 | `doc_id`, `doc_key`, `canonical_doc_id`, `canonical_doc_key`, `source_file`, `source_file_nfc`, `norm_name` |
| 파싱 상태 | `source_format`, `file_type`, `parser_status`, `parser`, `raw_char_len`, `clean_char_len`, `table_count`, `image_count`, `error` |
| 사업/기관 | `project_name`, `issuer` |
| 예산 | `final_budget`, `final_budget_krw`, `final_budget_status`, `final_budget_type`, `budget_candidate_count`, `threshold_budget_candidate_count` |
| 기간/보증 | `final_project_duration`, `final_maintenance_period`, `final_warranty_period` |
| 마감/공고 | `final_deadline_terms`, `final_notice_id`, `final_bid_deadline`, `bid_deadline_status` |
| 제출/자격 | `final_submission_documents`, `final_bid_eligibility_terms`, `business_type_candidates` |
| fact 품질 | `fact_status`, `fact_confidence`, `fact_block_count`, `embedded_table_block_count`, `suppressed_table_block_count` |
| preview | `text_preview_5000` |
| G2B 보강 | `g2b_match_status`, `g2b_match_score`, `g2b_bid_deadline`, `proposal_submission_date_hint`, `proposal_submission_method_hint`, `proposal_submission_place_hint` |

주요 결측 현황은 다음과 같다.

| 컬럼 | 결측 수 |
|---|---:|
| `project_name` | 0 |
| `issuer` | 0 |
| `text_preview_5000` | 0 |
| `final_budget_krw` | 158 |
| `final_project_duration` | 32 |
| `final_maintenance_period` | 605 |
| `final_warranty_period` | 367 |
| `final_deadline_terms` | 311 |
| `final_bid_deadline` | 607 |
| `final_submission_documents` | 41 |
| `final_bid_eligibility_terms` | 34 |

Phase 3 후보 생성에 활용 가능한 컬럼은 다음과 같다.

- 문서 식별: `source_file`, `source_file_nfc`, `doc_id`, `canonical_doc_id`
- 기본 식별: `project_name`, `issuer`
- 예산: `final_budget_krw`, `final_budget`, `final_budget_type`, `final_budget_status`
- 기간/마감: `final_project_duration`, `final_deadline_terms`, `final_bid_deadline`
- 제출/자격: `final_submission_documents`, `final_bid_eligibility_terms`
- 보증/유지보수: `final_maintenance_period`, `final_warranty_period`
- 참고 preview: `text_preview_5000`

주의할 점은 이 컬럼들이 자동 추출 또는 보강 결과라는 점이다. 공식 Phase 3 정답으로 쓰려면 사람이 검수해 `human_verified=true`, `review_status=verified` 상태로 확정해야 한다.

## 5. chunks_v2_690.jsonl 분석 결과

`new_data/chunks_v2_690.jsonl`은 130,304행이다. 모든 행에는 `chunk_id`, `doc_id`, `source_file`, `chunk_type`, `embed_enabled`, `content`, `metadata`, `source_ref`가 포함되어 있다.

기본 분포는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| 전체 row 수 | 130,304 |
| `embed_enabled=true` | 111,856 |
| `embed_enabled=false` | 18,448 |
| `chunk_type=text` | 26,506 |
| `chunk_type=table` | 97,261 |
| `chunk_type=fact_candidates` | 6,272 |
| `chunk_type=toc` | 265 |

`fact_candidates`는 중첩 리스트라기보다 `chunk_type=fact_candidates` 행에 `fact_type`, `answer_policy`, `answer_risk_level`, `budget_answer_enabled` 같은 key가 붙는 구조다. 따라서 Phase 3 후보 라벨 생성 시 `chunk_type=fact_candidates` 행을 필터링해서 사용하는 방식이 가장 단순하다.

주요 `fact_type` 분포는 다음과 같다.

| fact_type | count |
|---|---:|
| `document_summary` | 694 |
| `document_identity` | 690 |
| `business_type` | 690 |
| `eligibility` | 661 |
| `project_duration` | 658 |
| `submission_logistics` | 651 |
| `submission_documents` | 649 |
| `project_budget` | 498 |
| `deadline_term` | 379 |
| `warranty_period` | 323 |
| `threshold_budget` | 146 |
| `maintenance_period` | 85 |
| `bid_deadline` | 83 |
| `payment_terms` | 31 |
| `estimated_price` | 19 |
| `base_amount` | 15 |

`answer_policy` 분포는 다음과 같다.

| answer_policy | count | 해석 |
|---|---:|---|
| `question_type_dependent` | 4,494 | 질문 유형에 따라 사용 가능 여부 판단 필요 |
| `route_only_not_final_answer` | 690 | 문서 식별/라우팅용, 최종 답변 근거로 직접 사용 금지 |
| `allow_as_project_budget` | 498 | 사업 예산 답변 후보로 사용 가능 |
| `allow_for_deadline_questions_only` | 379 | 마감/기한 질문에 한정 |
| `allow_for_eligibility_exclude_for_project_budget` | 146 | 자격/기준 질문에는 가능하지만 사업금액 답변에는 부적절 |
| `allow_as_budget_when_project_budget_missing` | 34 | 사업예산 부재 시 보조 예산 후보 |
| `allow_for_payment_terms_exclude_for_project_budget` | 31 | 지급조건 질문에는 가능하지만 사업금액 답변에는 부적절 |

추가 flag 분포는 다음과 같다.

- `budget_answer_enabled=true`: 532
- `eligibility_answer_enabled=true`: 146
- `payment_answer_enabled=true`: 31
- `answer_risk_level=low`: 5,011
- `answer_risk_level=medium`: 1,261

중요한 해석은 다음과 같다.

- `project_budget`은 공식 사업금액 후보로 우선 검토할 수 있다.
- `threshold_budget`은 입찰자격 기준 금액일 수 있으므로 사업금액으로 답하면 감점 대상이다.
- `payment_terms`는 지급조건 질문에는 유용하지만 사업금액 답변에는 부적절하다.
- `base_amount`, `estimated_price`는 보조 예산 후보일 수 있으나 `project_budget`과 구분해야 한다.
- 모든 fact 후보는 정답이 아니라 검수 후보로만 사용한다.

## 6. validation_report_v2.json 분석 결과

`new_data/validation_report_v2.json`의 주요 결과는 다음과 같다.

| 항목 | 값 |
|---|---:|
| `document_count` | 690 |
| `parse_success_docs` | 690 |
| `parse_failed_docs` | 0 |
| `chunk_count` | 130,304 |
| `embed_enabled_count` | 111,856 |
| `status` | `PASS` |
| `fail_reasons` | `[]` |

이 결과가 Phase 3 설계에 주는 의미는 다음과 같다.

- 690개 문서 모두 파싱 성공이므로 후보 문서 풀은 충분하다.
- table chunk가 97,261개로 많아 RFP 특화 평가에서 예산, 제출서류, 자격요건처럼 표 기반 정보가 중요할 가능성이 높다.
- fact 후보가 6,272개로 많지만 검수 없이 gold label로 확정하면 안 된다.
- `budget_answer_enabled`, `eligibility_answer_enabled`, `payment_answer_enabled`는 답변 허용 범위를 구분하는 데 유용하다.
- Phase 3는 자동 후보 생성과 사람 검수를 분리해야 한다.

## 7. 기존 eval 500문항 분석 결과

canonical 후보 질문 풀은 `data/eval/eval_batch_01.csv`부터 `eval_batch_25.csv`까지 25개 파일, 총 500문항이다. 이 500문항은 Phase 3 정답지가 아니라 RFP 특화 pilot gold set을 만들기 위한 후보 질문 풀로 사용한다.

기본 구조는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| CSV 파일 수 | 25 |
| 전체 문항 수 | 500 |
| 고유 id 수 | 500 |
| id 범위 | `Q001` ~ `Q500` |
| 각 batch 행 수 | 20 |
| ground truth 고유 문서 수 | 41 |

type 분포는 A 150, B 200, C 50, D 50, E 50이다. difficulty 분포는 하 254, 중 155, 상 91이다.

`ground_truth_docs` 개수 분포는 다음과 같다.

| 정답 문서 수 | 문항 수 |
|---:|---:|
| 1 | 297 |
| 2 | 164 |
| 3 | 32 |
| 4 | 7 |

single-doc 문항은 297개, multi-doc 문항은 203개다. 실제 history가 비어 있지 않은 문항은 50개다.

후보 분류는 질문 텍스트와 기존 답변 텍스트를 이용해 사람이 선별하기 위한 1차 필터로만 사용한다. 기존 eval CSV의 `ground_truth_answer`를 Phase 3 정답 라벨로 그대로 쓰지 않는다. Phase 3에서는 `id`, `question`, `ground_truth_docs`는 유지하되, RFP 특화 구조화 정답 라벨은 별도 검수 파일에서 새로 확정한다.

## 8. Phase 3 RFP 특화 평가 설계

Phase 3의 목적은 RFP 답변에 실무적으로 중요한 필드가 정확히 포함되었는지 평가하는 것이다. Phase 1은 정답 문서 검색 여부를 보고, Phase 2는 RAGAS로 생성 답변의 근거성과 관련성을 본다. 그러나 RFP 실무에서는 다음 오류가 별도로 중요하다.

- 발주기관, 사업명, 사업금액, 사업기간 같은 필수 식별 정보 누락
- 사업금액과 추정가격, 기초금액, 입찰참가자격 기준금액 혼동
- 제출서류, 입찰자격, 마감일 같은 실무 항목 누락
- 여러 RFP 비교 질문에서 일부 문서만 다룸
- 문서에 없는 최종 낙찰업체, 계약 결과, 내부 의도 등을 단정

Phase 3는 처음부터 500문항 전체를 대상으로 하지 않는다. 먼저 50문항 pilot gold set을 만들고, 사람이 검수한 구조화 정답 라벨을 기준으로 평가한다.

## 9. 검수용 파일과 실제 평가용 파일 분리 정책

Phase 3 정답지는 검수용 파일과 실제 평가용 파일을 분리한다. 사람이 복잡한 JSONL을 직접 작성하지 않게 하고, 평가 코드는 안정적인 JSONL만 읽게 하기 위함이다.

최종 구조는 다음과 같다.

```text
eval/evaluation/data/
  rfp_domain_gold_candidates.csv
  rfp_domain_gold_review.xlsx
  rfp_domain_gold_sample.jsonl
```

### rfp_domain_gold_candidates.csv

`eval/evaluation/data/rfp_domain_gold_candidates.csv`는 canonical 500문항에서 Phase 3 후보로 선별된 문항 목록이다. 자동 후보 추출 결과를 담으며 사람 검수 전 단계다.

후보 컬럼은 다음과 같다.

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

### rfp_domain_gold_review.xlsx

`eval/evaluation/data/rfp_domain_gold_review.xlsx`는 사람이 검수하는 작업표다. candidate 값과 reviewer가 확정한 값을 함께 담는다.

검수 편의성을 위해 이 파일은 단일 sheet가 아니라 multi-sheet 구조로 설계한다. 모든 task_family를 한 sheet에 넣으면 컬럼이 과도하게 늘어나고, 검수자가 어떤 값을 확정해야 하는지 혼동하기 쉽다.

권장 sheet 구조는 다음과 같다.

| sheet | 목적 | 주요 검수 내용 |
|---|---|---|
| `README` | 검수 원칙 안내 | `review_status`, `human_verified`, 금지사항, 보안 원칙 |
| `candidates_all` | 자동 후보 전체 탐색 | 후보 문항, 후보 task_family, 후보 fact/chunk |
| `budget_review` | 예산/금액 질문 검수 | `project_budget`, `threshold_budget`, `base_amount`, `estimated_price`, `payment_terms` 구분 |
| `multi_doc_comparison_review` | 다중 문서 비교 검수 | 비교 대상 문서, 비교 축, 요구 출력 구조 |
| `required_fields_review` | 필수 필드 검수 | 발주기관, 사업명, 사업기간, 주요요구사항 |
| `submission_eligibility_deadline_review` | 제출/자격/마감 검수 | 제출서류 checklist, 입찰자격 checklist, 마감일 |
| `unanswerable_review` | 문서에 없는 질문 검수 | 답변 불가 여부, 허용 refusal, 금지 단정 |
| `robust_query_review` | 오타/구어체 견고성 검수 | 대응 원 질문, 같은 정답 문서, 같은 핵심 필드 |

후보 컬럼은 다음과 같다.

- `id`
- `task_family`
- `question`
- `type`
- `difficulty`
- `ground_truth_docs`
- `candidate_source_docs`
- `candidate_agencies`
- `candidate_project_names`
- `candidate_budget_values`
- `candidate_submission_documents`
- `candidate_eligibility_terms`
- `candidate_deadline`
- `reviewer_confirmed_source_docs`
- `reviewer_confirmed_agencies`
- `reviewer_confirmed_project_names`
- `reviewer_confirmed_budget_items`
- `reviewer_confirmed_required_fields`
- `reviewer_confirmed_submission_documents`
- `reviewer_confirmed_eligibility_terms`
- `reviewer_confirmed_deadline`
- `is_unanswerable`
- `allowed_refusal_phrases`
- `forbidden_hallucination_patterns`
- `review_status`
- `human_verified`
- `reviewer`
- `review_notes`

`review_status` 후보는 다음 네 가지다.

- `needs_review`
- `verified`
- `rejected`
- `needs_fix`

공식 Phase 3 평가에 들어가는 조건은 다음 두 가지를 모두 만족하는 것이다.

- `human_verified == true`
- `review_status == verified`

### rfp_domain_gold_sample.jsonl

`eval/evaluation/data/rfp_domain_gold_sample.jsonl`은 실제 Phase 3 평가 코드가 읽는 최종 정답지다.

정책은 다음과 같다.

- `human_verified=true`이고 `review_status=verified`인 문항만 포함한다.
- 사람이 직접 작성하는 파일이 아니라 검수용 xlsx/csv에서 변환 생성되는 파일로 설계한다.
- 공통 필드와 `task_family`별 gold block 구조를 사용한다.

## 10. Phase 3 task_family 정의

Phase 3는 모든 문항에 같은 필드를 강제로 평가하지 않는다. 질문별 `task_family`에 따라 필요한 gold block만 둔다.

사용할 `task_family` 후보는 다음과 같다.

| task_family | 목적 | 주 gold block |
|---|---|---|
| `budget` | 사업금액, 합산 예산, 단위 변환, 금액 혼동 평가 | `budget_gold`, 필요 시 `identity_gold` |
| `multi_doc_comparison` | 여러 문서 비교 시 문서 coverage와 비교 구조 평가 | `multi_doc_comparison_gold`, 필요 시 `budget_gold`, `required_field_gold` |
| `required_fields` | 발주기관, 사업명, 사업기간, 주요요구사항 등 필수 필드 평가 | `required_field_gold` |
| `submission_eligibility_deadline` | 제출서류, 입찰자격, 마감일 평가 | `submission_eligibility_deadline_gold` |
| `unanswerable` | 문서에 없는 질문에 대한 확인 불가 응답 평가 | `unanswerable_gold` |
| `robust_query_type_e` | 오타/구어체 질문이 같은 핵심 정답을 유지하는지 평가 | `robust_query_gold` |

발주기관, 사업명, 사업금액, 사업기간, 제출서류, 입찰자격, 마감일, 주요요구사항은 Phase 3에서 제거하지 않는다. 다만 모든 문항에 8개 항목을 강제로 넣지 않고, 질문 의도에 맞는 block에서 필요한 항목만 `required=true`로 지정한다.

## 11. Phase 3 gold schema

### 공통 필드

모든 JSONL record는 아래 공통 필드를 가진다.

- `id`
- `task_family`
- `question_type`
- `human_verified`
- `review_status`
- `source_docs`
- `identity_gold`
- `evidence_refs`
- `notes`

`identity_gold`에는 발주기관과 사업명을 둔다.

```json
{
  "identity_gold": {
    "agencies": ["검수된 발주기관"],
    "project_names": ["검수된 사업명"]
  }
}
```

`identity_gold`는 기본적으로 문서/사업 식별용 공통 gold다. `identity_gold`에 값이 있다고 해서 항상 점수화하지 않는다. 실제 점수에 포함하려면 `required_field_gold.fields` 안에 `field_name=agency` 또는 `field_name=project_name`으로 명시해야 한다.

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

위 예시에서는 agency가 `required_field_gold`에 있으므로 점수화한다. 반대로 `identity_gold`에만 있으면 문서/사업 식별 참고 정보로만 사용한다.

`evidence_refs`는 긴 RFP 본문이 아니라 `source_file`, `chunk_id`, 짧은 `evidence_summary`만 담는다.

### budget_gold

예산/금액 질문에 사용한다.

포함 필드는 다음과 같다.

- `items`
- `total_krw`
- `budget_unit`
- `tolerance_krw`
- `tolerance_ratio`
- `excluded_budget_candidates`

각 item에는 다음을 포함한다.

- `label`
- `amount_krw`
- `budget_source_type`
- `source_file`
- `chunk_id`
- `evidence_summary`

`budget_source_type` 허용 후보는 다음과 같다.

- `project_budget`
- `base_amount`
- `estimated_price`
- `threshold_budget`
- `payment_terms`
- `unknown`

공식 사업금액으로 사용할 수 있는 것은 기본적으로 `project_budget`이다. `threshold_budget`, `base_amount`, `estimated_price`, `payment_terms`를 `project_budget`으로 잘못 사용하면 감점 대상으로 설계한다. 혼동하면 안 되는 금액 후보는 `excluded_budget_candidates`에 넣는다.

다만 실제 RFP에서는 `project_budget`이 명확히 없고 `estimated_price` 또는 `base_amount`만 기준 금액처럼 제시되는 경우가 있을 수 있다. 이 경우 사람이 해당 질문의 기준 금액으로 검수한 경우에만 예외적으로 허용한다. 예외 승인 여부와 이유는 `budget_review` sheet의 `budget_exception_approved`, `budget_exception_reason`, `review_notes`에 남긴다.

`budget_source_type` 판정 규칙은 다음과 같다.

| budget_source_type | 기본 사업금액 답변 사용 | 예외 사용 가능 여부 | 설명 |
|---|---|---|---|
| `project_budget` | 가능 | 기본값 | 사업금액/예산으로 검수된 값 |
| `estimated_price` | 원칙적으로 보조 | 사람 검수 시 가능 | `project_budget` 부재 시 기준 금액으로 승인 가능 |
| `base_amount` | 원칙적으로 보조 | 사람 검수 시 가능 | `project_budget` 부재 시 기준 금액으로 승인 가능 |
| `threshold_budget` | 불가 | 자격요건 질문에서만 가능 | 입찰참가자격 기준 금액일 수 있음 |
| `payment_terms` | 불가 | 지급조건 질문에서만 가능 | 사업금액이 아니라 지급 조건 |
| `unknown` | 불가 | 검수 필요 | 공식 평가 제외 또는 `needs_fix` |

사업금액 질문에서 `threshold_budget`을 답하면 치명 오류 후보로 본다. `payment_terms`는 지급조건 질문에서는 유용하지만 사업금액으로 쓰면 안 된다.

```json
{
  "budget_gold": {
    "items": [
      {
        "label": "A 사업",
        "amount_krw": 1000000000,
        "budget_source_type": "project_budget",
        "source_file": "A.hwp",
        "chunk_id": "chunk_A",
        "evidence_summary": "사업금액 표기 확인"
      }
    ],
    "total_krw": 1000000000,
    "budget_unit": "KRW",
    "tolerance_krw": 0,
    "tolerance_ratio": 0.0,
    "excluded_budget_candidates": [
      {
        "amount_krw": 500000000,
        "budget_source_type": "threshold_budget",
        "reason": "입찰참가자격 기준 금액이므로 사업금액으로 사용 금지"
      }
    ]
  }
}
```

### required_field_gold

발주기관, 사업명, 사업기간, 주요요구사항 등 필수 필드 평가에 사용한다.

각 field에는 다음을 포함한다.

- `field_name`
- `match_type`
- `expected_value` 또는 `expected_values`
- `expected_keywords`
- `min_match_count`
- `required`
- `weight`
- `evidence_refs`

지원 `match_type`은 다음으로 제한한다.

- `exact`
- `exact_or_alias`
- `numeric_krw`
- `date`
- `keyword_coverage`
- `checklist_coverage`

v0에서는 semantic 자유평가를 최소화한다. 주요요구사항처럼 의미 요약이 필요한 항목은 `keyword_coverage` 또는 `checklist_coverage`로 제한하고, 자유 서술 의미 평가는 Phase 4 LLM Judge로 넘긴다.

```json
{
  "required_field_gold": {
    "fields": [
      {
        "field_name": "project_duration",
        "match_type": "keyword_coverage",
        "expected_keywords": ["착수일", "완료일", "개월"],
        "min_match_count": 2,
        "required": true,
        "weight": 1.0,
        "evidence_refs": [
          {
            "source_file": "A.hwp",
            "chunk_id": "chunk_duration_A",
            "evidence_summary": "사업기간 항목"
          }
        ]
      },
      {
        "field_name": "major_requirements",
        "match_type": "checklist_coverage",
        "expected_values": ["인프라 고도화", "운영 안정성", "업무 효율화"],
        "required": true,
        "weight": 1.0,
        "evidence_refs": []
      }
    ]
  }
}
```

### submission_eligibility_deadline_gold

제출서류, 입찰자격, 마감일 질문에 사용한다.

포함 필드는 다음과 같다.

- `submission_documents`
- `eligibility_terms`
- `deadline`
- `deadline_type`
- `evidence_refs`

평가는 `checklist_coverage`, `keyword_coverage`, `date` match 중심으로 설계한다. 제출서류와 입찰자격은 목록이 길 수 있으므로 전체 원문을 넣지 않고 검수된 짧은 항목 목록만 둔다.

### unanswerable_gold

문서에 없는 질문에 사용한다.

포함 필드는 다음과 같다.

- `is_unanswerable`
- `allowed_refusal_phrases`
- `forbidden_claim_types`
- `forbidden_hallucination_patterns`

```json
{
  "unanswerable_gold": {
    "is_unanswerable": true,
    "allowed_refusal_phrases": ["확인할 수 없습니다", "명시되어 있지 않습니다", "제공된 자료에는 없습니다"],
    "forbidden_claim_types": ["낙찰업체 단정", "계약결과 단정", "내부 의도 단정"],
    "forbidden_hallucination_patterns": []
  }
}
```

### multi_doc_comparison_gold

다중 문서 비교 질문에 사용한다. v0에서는 복잡한 의미 평가를 피하고 구조적 요건만 평가한다.

포함 필드는 다음과 같다.

- `compared_docs`
- `required_doc_coverage`
- `required_comparison_axes`
- `required_output_structure`

```json
{
  "multi_doc_comparison_gold": {
    "compared_docs": ["A.hwp", "B.hwp", "C.hwp"],
    "required_doc_coverage": 3,
    "required_comparison_axes": ["예산", "사업목표", "주요요구사항"],
    "required_output_structure": ["공통점", "차이점", "문서별 요약"]
  }
}
```

공통점/차이점의 의미적 품질은 Phase 4에서 평가한다.

### robust_query_gold

type E 오타/구어체 견고성 질문에 사용한다.

포함 필드는 다음과 같다.

- `canonical_question_id` 또는 `related_original_id`
- `expected_same_source_docs`
- `expected_same_key_fields`

v0에서는 robust query가 원 질문과 같은 정답 문서와 핵심 필드를 유지하는지 정도만 평가한다.

## 12. Phase 3 공식 지표 정의

Phase 3 v0 공식 지표는 아래 세 개 중심으로 설계한다.

- `required_field_accuracy`
- `budget_numeric_accuracy`
- `unanswerable_refusal_accuracy`

이 말은 평가 항목을 삭제한다는 뜻이 아니다. 발주기관, 사업명, 사업금액, 사업기간, 제출서류, 입찰자격, 마감일, 주요요구사항은 gold schema에 유지하되, 문항별 `required_field_gold` 또는 task_family별 gold block 안에서 필요한 항목만 평가한다.

### required_field_accuracy

계산 방식은 다음과 같다.

- 문항별 `required_field_gold.fields`에 들어 있는 필드만 평가한다.
- 각 field는 `weight`를 가진다.
- `matched_weight / total_required_weight`로 점수를 계산한다.
- `required=false`인 optional field는 공식 점수에 넣지 않고 보조 분석으로만 기록한다.

지원 match 방식은 다음과 같다.

- `exact`
- `exact_or_alias`
- `numeric_krw`
- `date`
- `keyword_coverage`
- `checklist_coverage`

주요요구사항은 v0에서 `keyword_coverage` 또는 `checklist_coverage`로 제한한다. 의미적 자유 평가는 Phase 4로 넘긴다.

### budget_numeric_accuracy

계산 방식은 다음과 같다.

- 답변에서 숫자와 단위를 추출해 KRW로 정규화한다.
- `budget_gold.items`와 비교한다.
- 합산 질문은 item별 금액과 `total_krw`를 모두 확인한다.
- `tolerance_krw` 또는 `tolerance_ratio`를 적용할 수 있다.
- `threshold_budget`, `base_amount`, `estimated_price`, `payment_terms`를 `project_budget`으로 오인하면 감점한다.

예산 평가 제외 조건은 다음과 같다.

- expected budget이 검수되지 않음
- `budget_source_type`이 불명확함
- `final_budget_krw` 또는 `project_budget` 후보가 없음
- `human_verified=false`
- `review_status != verified`

### unanswerable_refusal_accuracy

계산 방식은 다음과 같다.

- `unanswerable_gold.is_unanswerable=true`인 문항만 평가한다.
- 답변에 `allowed_refusal_phrases`가 포함되면 긍정 평가한다.
- `forbidden_hallucination_patterns` 또는 `forbidden_claim_types`에 해당하는 단정이 있으면 감점한다.
- 확인 불가라고 말했지만 추측을 덧붙이면 부분 점수로 둔다.

### v0 보조 분석 metric

`multi_doc_comparison`과 `robust_query_type_e`는 pilot 50문항에 포함되지만, v0 공식 Phase 3 대표 평균에는 넣지 않는 것을 우선 제안한다. 두 task는 구조적 보조 분석 컬럼으로 기록하고, 추후 채점 안정성이 확인되면 공식 지표 편입 여부를 다시 판단한다.

#### multi_doc_structure_score

목적은 다중 문서 비교 질문에서 모든 문서를 다뤘는지, 비교 축과 출력 구조를 지켰는지 보는 것이다.

평가 후보는 다음과 같다.

- `doc_coverage_score`: `compared_docs` 중 답변에서 다룬 문서 비율
- `comparison_axis_score`: `required_comparison_axes` 언급 여부
- `output_structure_score`: `required_output_structure` 충족 여부

초기에는 `phase3_results.csv`의 보조 컬럼으로만 기록하고, `required_field_accuracy`, `budget_numeric_accuracy`, `unanswerable_refusal_accuracy`의 공식 평균에는 포함하지 않는다.

#### robust_query_consistency_score

목적은 오타/구어체 질문에서도 원 질문과 같은 정답 문서와 핵심 필드를 유지하는지 보는 것이다.

평가 후보는 다음과 같다.

- `same_source_doc_match`: `expected_same_source_docs` 유지 여부
- `same_key_field_match`: `expected_same_key_fields` 유지 여부

초기에는 보조 컬럼으로만 기록하고 공식 Phase 3 평균에는 포함하지 않는다.

## 13. Phase 3 pilot gold set 50문항 구성 전략

Phase 3 pilot gold set은 50문항으로 고정한다.

| task_family | 문항 수 | 목적 |
|---|---:|---|
| `budget` | 12 | 단일/합산 예산, 단위 변환, 금액 혼동 평가 |
| `multi_doc_comparison` | 10 | 여러 문서 비교, 공통점/차이점 구조 평가 |
| `required_fields` | 10 | 발주기관, 사업명, 사업기간, 주요요구사항 등 필수 필드 평가 |
| `submission_eligibility_deadline` | 8 | 제출서류, 입찰자격, 마감일 평가 |
| `unanswerable` | 7 | 문서에 없는 질문 대응 평가 |
| `robust_query_type_e` | 3 | 오타/구어체 견고성 평가 |

조건은 다음과 같다.

- 50문항 모두 사람이 검수해야 한다.
- `human_verified=true`가 아닌 문항은 공식 Phase 3 평가에 사용하지 않는다.
- `review_status=verified`가 아닌 문항은 공식 Phase 3 평가에 사용하지 않는다.
- fact 후보는 후보일 뿐이며 정답으로 자동 확정하지 않는다.
- 예산 문항은 `final_budget_krw` 또는 `project_budget` 후보가 있고 사람이 `budget_source_type`을 확인한 경우만 선택한다.
- multi-doc 문항은 `ground_truth_docs`가 2개 이상인 문항을 우선한다.
- unanswerable 문항은 type D를 우선 후보로 하되, 실제로 문서에서 답변 불가능한지 검수한다.

## 14. Phase 3 구현 우선순위

Phase 3 구현은 다음 순서가 적절하다.

1. `eval/evaluation/data/rfp_domain_gold_candidates.csv` 생성 로직 설계
2. `rfp_domain_gold_review.xlsx` 검수 양식 확정
3. review 파일에서 `human_verified=true`, `review_status=verified` 행만 JSONL로 변환하는 절차 설계
4. `rfp_domain_gold_sample.jsonl` schema validator 설계
5. `required_field_accuracy` 계산 설계
6. `budget_numeric_accuracy` 계산 설계
7. `unanswerable_refusal_accuracy` 계산 설계
8. Phase 1/2 결과와 Phase 3 결과 병합 설계
9. Phase 3 experiment log append 설계
10. failure analysis에서 Phase 3 실패 사유 추가

구현 전까지 기존 Phase 1/2 코드와 정책은 수정하지 않는다.

## 15. Phase 4 LLM API 기반 종합 평가 설계

Phase 4는 LLM API 기반 종합 평가다. 목적은 Phase 1~3으로 잡기 어려운 실무적 답변 품질을 보조적으로 평가하는 것이다. Phase 4는 Phase 1/2 공식 점수의 대체재가 아니다.

Phase 4는 독립 judge 평가로 설계한다. 따라서 judge prompt 입력에서 다음을 제거한다.

- `phase1_metrics`
- `phase2_ragas_metrics`
- `phase3_domain_metrics`

이유는 LLM Judge가 기존 점수를 보고 따라가면 독립성이 깨지기 때문이다. Phase 1~3 metric은 judge 입력에 넣지 않고, 최종 report aggregator에서 함께 해석한다.

Phase 4 입력에 넣는 정보는 아래로 제한한다.

- `id`
- `question`
- `rag_answer`
- `ground_truth_answer_summary`
- `expected_source_docs`
- `retrieved_evidence_summaries`
- `domain_gold_summary`, optional

원본 RFP 전문, 긴 table, source_store 전체, 긴 context는 넣지 않는다.

`domain_gold_summary`는 사람이 새로 쓰는 것이 아니라 Phase 3 gold JSONL에서 자동 생성한다. 생성 규칙은 다음과 같다.

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

이 요약은 judge 입력을 돕기 위한 짧은 구조화 정보일 뿐이며, Phase 1~3 metric 점수는 포함하지 않는다.

## 16. Phase 4 rubric

Phase 4는 다음 항목을 평가한다.

| 항목 | 의미 | 1점 | 3점 | 5점 |
|---|---|---|---|---|
| `business_usefulness` | 입찰 컨설턴트가 바로 활용할 수 있는 답변인지 | 실무 사용이 어렵거나 위험함 | 일부 유용하지만 보완 필요 | 바로 참고 가능한 구조와 내용 |
| `completeness` | 질문이 요구한 항목을 빠뜨리지 않았는지 | 핵심 항목 대부분 누락 | 일부 누락 또는 불균형 | 요구 항목을 빠짐없이 다룸 |
| `groundedness` | 제공된 요약 근거를 벗어나지 않았는지 | 문서 밖 내용을 단정 | 대부분 근거 기반이나 일부 추정 | 근거 안에서만 답변 |
| `numeric_correctness` | 금액, 합산, 단위, 날짜가 정확한지 | 숫자/단위 오류가 치명적 | 일부 표기 또는 계산 오류 | 숫자와 단위가 정확 |
| `comparison_quality` | 여러 RFP 비교 시 공통점과 차이점을 명확히 구분했는지 | 비교 구조가 없거나 한 문서만 다룸 | 일부 비교 가능하나 불명확 | 공통점/차이점/결론이 명확 |
| `risk_level` | 실무적으로 위험한 답변인지 | `high` | `medium` | `low` |

감점 원칙은 다음과 같다.

- 문서에 없는 낙찰 업체, 계약 결과, 내부 의도, 법적 판단을 단정하면 `groundedness`와 `risk_level`에서 강하게 감점한다.
- 예산, 합산, 단위, 날짜 오류는 치명 오류로 본다.
- 다중 문서 비교 질문에서 하나의 문서만 다루면 `completeness`와 `comparison_quality`를 감점한다.
- 유창하지만 근거가 약한 답변은 높은 점수를 주지 않는다.

## 17. Phase 4 JSON 출력 schema

LLM Judge는 `overall_score`를 직접 출력하지 않는다. 세부 항목만 평가하고, `overall_score`는 코드에서 계산한다.

LLM Judge 출력 schema는 다음과 같다.

```json
{
  "id": "Q123",
  "business_usefulness": 5,
  "completeness": 4,
  "groundedness": 4,
  "numeric_correctness": 3,
  "comparison_quality": 4,
  "risk_level": "medium",
  "critical_errors": [],
  "judge_comment": "짧은 한국어 평가 이유"
}
```

제약 조건은 다음과 같다.

- `business_usefulness`, `completeness`, `groundedness`, `numeric_correctness`, `comparison_quality`는 1~5 정수다.
- `risk_level`은 `low`, `medium`, `high` 중 하나다.
- `critical_errors`는 문자열 배열이다.
- `judge_comment`는 짧은 한국어 설명이다.
- JSON 외 텍스트를 출력하지 않는다.
- 원본 context나 RFP 본문을 길게 복사하지 않는다.

## 18. Phase 4 overall_score 코드 계산 방식

`overall_score`는 LLM이 아니라 평가 코드에서 계산한다. 기본 가중합 설계안은 다음과 같다.

```text
overall_score =
0.20 * business_usefulness
+ 0.25 * completeness
+ 0.25 * groundedness
+ 0.20 * numeric_correctness
+ 0.10 * comparison_quality
```

cap rule 설계안은 다음과 같다.

- `groundedness <= 2`이면 `overall_score` 최대 2.5
- `numeric_correctness <= 2`이면 `overall_score` 최대 2.5
- `risk_level == high`이면 `overall_score` 최대 2.0
- `critical_errors`가 있으면 오류 종류에 따라 cap 적용

이 방식은 LLM Judge가 전체 점수를 자의적으로 결정하지 않게 하고, 세부 항목 점수와 최종 점수 사이의 일관성을 높이기 위한 설계다.

## 19. Phase 4 Judge Prompt 초안

### System prompt

```text
당신은 RFP 입찰 컨설팅 QA 평가자입니다.
당신의 임무는 RAG 시스템의 답변이 실무적으로 신뢰할 수 있는지 평가하는 것입니다.

평가에서는 답변의 유창함보다 문서 근거성, 완전성, 숫자 정확성, 비교 품질을 우선합니다.
문서에 없는 내용을 단정하면 강하게 감점합니다.
금액, 합산, 단위, 날짜 오류는 치명 오류로 봅니다.
질문이 여러 문서를 비교하라고 했는데 답변이 하나의 문서만 다루면 completeness와 comparison_quality를 낮게 평가합니다.

기존 Phase 1, Phase 2, Phase 3 점수는 제공되지 않으며, 당신은 아래 입력만 보고 독립적으로 평가해야 합니다.
반드시 JSON만 출력하십시오.
JSON 밖에 설명, Markdown, 코드블록을 쓰지 마십시오.
judge_comment는 짧은 한국어 평가 이유만 작성하십시오.
원본 context를 길게 복사하지 마십시오.
```

### User prompt template

```text
다음 RAG 답변을 평가하십시오.

[평가 기준]
- business_usefulness: 입찰 컨설턴트가 바로 활용할 수 있는가
- completeness: 질문이 요구한 항목을 빠뜨리지 않았는가
- groundedness: 제공된 ground truth summary와 evidence summary를 벗어나지 않았는가
- numeric_correctness: 금액, 합산, 단위, 날짜가 정확한가
- comparison_quality: 여러 문서 비교 질문에서 공통점과 차이점을 명확히 구분했는가
- risk_level: 실무적으로 위험한 단정이나 환각이 있는가

[출력 JSON schema]
{
  "id": "문항 id",
  "business_usefulness": 1~5 정수,
  "completeness": 1~5 정수,
  "groundedness": 1~5 정수,
  "numeric_correctness": 1~5 정수,
  "comparison_quality": 1~5 정수,
  "risk_level": "low|medium|high",
  "critical_errors": ["오류 목록"],
  "judge_comment": "짧은 한국어 평가 이유"
}

[입력]
id: {id}
question: {question}
rag_answer: {rag_answer}
ground_truth_answer_summary: {ground_truth_answer_summary}
expected_source_docs: {expected_source_docs}
retrieved_evidence_summaries: {retrieved_evidence_summaries}
domain_gold_summary: {domain_gold_summary}

[주의]
- 제공된 evidence summary와 ground truth summary에 없는 내용을 답변이 단정하면 groundedness를 낮게 주십시오.
- 숫자, 예산, 단위, 날짜 오류가 있으면 numeric_correctness를 낮게 주고 critical_errors에 기록하십시오.
- 문서에 없는 정보를 물은 질문에서 답변이 확인 불가라고 말하지 않으면 risk_level을 high로 둘 수 있습니다.
- 기존 Phase 1, Phase 2, Phase 3 점수는 입력에 포함하지 않습니다.
- JSON 외의 텍스트를 출력하지 마십시오.
```

## 20. Phase 4 입력 길이 제한

Phase 4 입력 길이는 다음처럼 제한한다.

| 입력 항목 | 제한 |
|---|---:|
| `ground_truth_answer_summary` | 최대 700자 |
| `retrieved_evidence_summaries` | 최대 5개 |
| evidence summary 1개 | 최대 300자 |
| `rag_answer` | 최대 1,500자 |
| `source_store` 전체 | 금지 |
| 긴 table 원문 | 금지 |
| 원본 RFP 전문 | 금지 |

이 제한의 이유는 다음과 같다.

- 보안: 원본 RFP와 긴 context 외부 유출 방지
- 비용: LLM API token 비용 통제
- 평가 일관성: judge가 과도한 정보에 끌려가지 않게 함
- 후처리 안정성: 입력 길이 편차로 인한 평가 변동성 감소

## 21. Phase 4 보안/데이터 정책

Phase 4는 LLM API를 사용할 수 있으므로 다음 정책을 반드시 지킨다.

- 원본 RFP 전문을 외부 LLM API에 보내지 않는다.
- `source_store` 전체를 보내지 않는다.
- 긴 table 원문을 보내지 않는다.
- API key 값은 어떤 로그에도 저장하지 않는다.
- 요청/응답 로그에 원문 context를 과도하게 저장하지 않는다.
- 외부 API 사용 전 팀/멘토 승인 필요하다.
- 외부 API 사용이 승인되지 않으면 Phase 4는 설계만 유지하고 실행하지 않는다.
- judge model, prompt version, rubric version, temperature, sample size는 기록하되 secret 값은 기록하지 않는다.

## 22. 실험 로그 확장 방안

현재 experiment logs는 append-only 정책을 사용한다. Phase 3/4도 같은 방식을 유지한다.

제안 로그 파일은 다음과 같다.

```text
eval/evaluation/outputs/eval/experiment_logs/phase3_domain_experiments.csv
eval/evaluation/outputs/eval/experiment_logs/phase4_llm_judge_experiments.csv
```

Phase 3 로그 후보 컬럼은 다음과 같다.

- `experiment_id`
- `experiment_name`
- `run_datetime`
- `notes`
- `gold_candidates_path`
- `gold_review_path`
- `gold_jsonl_path`
- `gold_sample_size`
- `human_verified_count`
- `required_field_accuracy_mean`
- `budget_numeric_accuracy_mean`
- `unanswerable_refusal_accuracy_mean`
- `phase3_error_count`

Phase 4 로그 후보 컬럼은 다음과 같다.

- `experiment_id`
- `experiment_name`
- `run_datetime`
- `notes`
- `judge_provider`
- `judge_model`
- `prompt_version`
- `rubric_version`
- `temperature`
- `sample_size`
- `input_length_policy_version`
- `overall_score_mean`
- `business_usefulness_mean`
- `completeness_mean`
- `groundedness_mean`
- `numeric_correctness_mean`
- `comparison_quality_mean`
- `risk_level_low_count`
- `risk_level_medium_count`
- `risk_level_high_count`
- `critical_error_count`
- `api_error_count`

로그에는 API key, 긴 RFP 본문, 긴 context, source_store 원문을 저장하지 않는다.

## 23. 외부 리서치 출처와 설계 반영점

외부 자료는 방법론 참고용으로만 사용한다. 내부 RFP 데이터나 원문은 외부로 보내지 않는다.

| 출처 | 문서에서 반영한 설계 원칙 |
|---|---|
| [MT-Bench/Chatbot Arena](https://arxiv.org/abs/2306.05685) | LLM Judge의 편향과 한계를 인식하고, Phase 4를 공식 점수 대체재가 아닌 보조 평가로 둔다. |
| [G-Eval](https://arxiv.org/abs/2303.16634) | rubric/form-filling 기반 평가 설계를 참고해 항목별 점수를 고정한다. |
| [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat) | JSON schema 고정과 후처리 안정성 확보 원칙을 반영한다. |
| [OpenAI Evals Cookbook](https://cookbook.openai.com/examples/evaluation/getting_started_with_openai_evals) | ideal answer 기반 model-graded evaluation 아이디어를 참고하되, 내부 데이터는 짧은 summary로 제한한다. |

## 24. 구현하지 않고 남겨둘 항목

이번 설계 문서 작성 단계에서 구현하지 않는 항목은 다음과 같다.

- Phase 3/4 평가 코드
- `rfp_domain_gold_candidates.csv`, `rfp_domain_gold_review.xlsx`, `rfp_domain_gold_sample.jsonl` 실제 생성 코드
- Phase 4 LLM API 호출 코드
- Phase 4 LLM Judge 결과를 단독 공식 점수로 사용하는 것
- Phase 3 `human_verified=false` 라벨을 공식 평가에 사용하는 것
- Phase 4 prompt에 기존 Phase 1~3 metric 점수를 넣는 것
- fact 후보를 검수 없이 정답으로 확정하는 것
- 사람이 직접 복잡한 JSONL을 수작업으로 작성하는 것
- 모든 문항에 모든 required field를 강제로 적용하는 것
- `multi_doc_structure_score`, `robust_query_consistency_score`를 검증 없이 공식 Phase 3 대표 평균에 포함하는 것
- `identity_gold`에 있다는 이유만으로 agency/project_name을 자동 감점 기준으로 쓰는 것
- `domain_gold_summary`를 사람이 자유 서술로 새로 작성하는 것
- 500문항 전체에 Phase 3 지표를 바로 적용하는 것
- 원본 RFP 전문을 외부 LLM API에 보내는 것
- Phase 1/2 공식 지표 변경
- `hit@1`, `hit@3`, `doc_recall@k`, `chunk_hit@k` 재도입

## 25. 다음 Codex 작업 프롬프트 초안

```text
너는 AI 중급 프로젝트의 RAG 평가 모듈 Phase 3 후보 라벨 생성 설계 담당 보조 에이전트다.

먼저 AGENTS.md, eval/evaluation/AGENTS.md, eval/evaluation/README.md,
eval/evaluation/docs/phase3_phase4_eval_plan.md를 읽고 현재 평가 정책을 확인하라.

중요:
- 기존 Phase 1/2 정책을 변경하지 마라.
- Phase 1 metric은 hit_at_5, mrr_at_5, ndcg_at_5만 유지한다.
- Phase 2 RAGAS 기본 evaluator 정책을 변경하지 마라.
- 원본 RFP 본문과 API key를 로그/리포트에 저장하지 마라.
- fact_candidates는 정답 후보일 뿐이며, human_verified=true와 review_status=verified인 gold label만 공식 Phase 3 평가에 사용한다.

작업 목표:
1. eval/evaluation/data/rfp_domain_gold_candidates.csv 생성 규칙을 설계한다.
2. eval/evaluation/data/rfp_domain_gold_review.xlsx 검수 양식을 설계한다.
3. 검수용 xlsx/csv에서 eval/evaluation/data/rfp_domain_gold_sample.jsonl로 변환하는 절차를 설계한다.
4. task_family별 gold block schema validator 계획을 작성한다.
5. 아직 코드는 구현하지 말고, 후보 선정 기준과 검수 절차 문서를 먼저 작성한다.
```
