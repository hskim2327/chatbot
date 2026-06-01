# Phase 3 최종 gold JSONL 생성 리포트

## 최종 상태 요약

이 문서에는 초기 생성 당시 상태와 warning resolution 이후 상태가 함께 기록되어 있다. 현재 Phase 3 평가 구현에서 기준으로 삼아야 하는 최종 상태는 아래 값이다.

- record 수: 50
- id 고유 수: 50
- `complete`: 49
- `complete_with_warnings`: 1
- `needs_fix`: 0
- `can_use_for_phase3=false`: 0
- `warning_resolution_status.resolved`: 13
- `warning_resolution_status.accepted_warning`: 1
- `warning_resolution_status.unresolved_needs_fix`: 0

아래의 기존 기록 중 warning 14개 목록은 초기 생성 당시 상태다. warning resolution 이후에는 13개가 해결되었고, 1개는 `accepted_warning`으로 분류되었다.

## 초기 생성 당시 상태
# Phase 3 최종 gold JSONL 생성 리포트

## 1. 작업 목적

`hybrid_50` 50문항을 사용자 batch approval에 따라 Phase 3 pilot gold set으로 변환했다.

## 2. 사용자 batch approval 반영 방식

- `human_verified=true`
- `review_status=verified`
- `final_use_decision=keep`
- `verification_method=batch_user_approval_from_hybrid_50`
- `reviewer=project_owner_batch_approval`
- `review_notes=User approved hybrid_50 as Phase 3 pilot gold set without row-level Excel edits.`

## 3. record 수와 id 고유성

- JSONL record 수: 50
- id 고유 수: 50

## 4. task_family별 record 수

- `budget`: 12
- `multi_doc_comparison`: 10
- `required_fields`: 8
- `submission_eligibility_deadline`: 7
- `unanswerable`: 10
- `robust_query_type_e`: 3

## 5. gold block별 생성 수

- `budget_gold`: 12
- `multi_doc_comparison_gold`: 10
- `required_field_gold`: 8
- `submission_eligibility_deadline_gold`: 7
- `unanswerable_gold`: 10
- `robust_query_gold`: 3

## 6. gold_generation_status 분포

- `complete`: 36
- `complete_with_warnings`: 14

## 7. can_use_for_phase3=false 문항

- 없음

## 8. warning이 있는 문항

- `Q067`: evidence_refs가 비어 있음
- `Q068`: evidence_refs가 비어 있음
- `Q069`: evidence_refs가 비어 있음
- `Q071`: evidence_refs가 비어 있음
- `Q072`: evidence_refs가 비어 있음
- `Q025`: evidence_refs가 비어 있음
- `Q042`: evidence_refs가 비어 있음
- `Q395`: evidence_refs가 비어 있음
- `P3-SUB-001`: candidate 값에 noisy flag가 있음
- `P3-SUB-004`: question rewrite가 필요한 extension 후보임
- `P3-SUB-010`: question rewrite가 필요한 extension 후보임
- `Q019`: canonical_question_id/related_original_id가 모두 비어 있음
- `Q020`: canonical_question_id/related_original_id가 모두 비어 있음
- `Q039`: canonical_question_id/related_original_id가 모두 비어 있음


## 9. 생성 산출물

- `eval/evaluation/data/rfp_domain_gold_sample.jsonl`
- `eval/evaluation/data/rfp_domain_gold_sample.xlsx`
- `eval/evaluation/data/rfp_domain_gold_sample_readable.csv`
- `eval/evaluation/data/rfp_domain_gold_sample_validation.csv`
- `eval/evaluation/data/rfp_domain_gold_hybrid_50_approved.csv`
- `eval/evaluation/docs/rfp_domain_gold_sample_guide.md`

## 10. cleanup 정보

- 삭제 후보 수: 16
- 삭제한 파일 수: 15
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_candidates.csv`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_selected_50.csv`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_phase3_extension_candidates.csv`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_hybrid_50_recommendation.csv`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_review.xlsx`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_candidate_generation_report.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_selected_50_report.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_extension_candidate_report.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_extension_quality_and_hybrid_report.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_hybrid_50_review_checklist.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_hybrid_50_review_preparation_report.md`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\build_phase3_gold_review_assets.py`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\select_phase3_gold_50.py`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\build_phase3_extension_candidates.py`
- 삭제: `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\review_phase3_extension_quality_and_hybrid.py`

## 11. 주의사항

없는 정답값은 새로 만들지 않았고, 부족하거나 불확실한 값은 warning으로 남겼다. 원본 RFP 전문, 긴 table, source_store 전체, secret 값은 산출물에 넣지 않았다.

## Warning resolution pass

Phase 3 Gold Warning Resolution 작업을 수행했다.

- 기존 warning 문항 수: 14
- resolved: 13
- accepted_warning: 1
- unresolved_needs_fix: 0
- 최종 status 분포: {'complete': 49, 'complete_with_warnings': 1}
- can_use_for_phase3=false 문항: 없음

