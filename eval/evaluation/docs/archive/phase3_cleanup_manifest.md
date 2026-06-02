# Phase 3 cleanup manifest

## 1. 정리 목적

Phase 3 최종 gold 산출물이 생성된 뒤 중간 후보 파일을 정리해 평가 폴더를 단순화한다.

## 2. 보존 파일 목록

- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_sample.jsonl`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_sample.xlsx`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_sample_readable.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_sample_validation.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_hybrid_50_approved.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\rfp_domain_gold_sample_guide.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_gold_jsonl_generation_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_cleanup_manifest.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\build_phase3_gold_sample_jsonl.py`
- `eval\evaluation\README.md`
- `eval\evaluation\AGENTS.md`
- `eval\evaluation\src`
- `eval\evaluation\scripts\run_evaluation.py`
- `eval\evaluation\tests`
- `eval\evaluation\requirements.txt`
- `eval\evaluation\docs\evaluation_plan.md`
- `eval\evaluation\docs\evaluation_refactor_plan.md`
- `eval\evaluation\docs\phase3_phase4_eval_plan.md`

## 3. 삭제한 파일 목록

- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_candidates.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_selected_50.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_phase3_extension_candidates.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_hybrid_50_recommendation.csv`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\data\rfp_domain_gold_review.xlsx`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_candidate_generation_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_selected_50_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_extension_candidate_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_extension_quality_and_hybrid_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_hybrid_50_review_checklist.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\docs\phase3_hybrid_50_review_preparation_report.md`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\build_phase3_gold_review_assets.py`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\select_phase3_gold_50.py`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\build_phase3_extension_candidates.py`
- `C:\Users\jolee\OneDrive\바탕 화면\AI엔지니어\중급 프로젝트\eval\evaluation\scripts\review_phase3_extension_quality_and_hybrid.py`


## 4. 삭제하지 않은 파일 목록과 이유

- 삭제 후보 파일이 남아 있지 않음

## 5. 삭제 전 검증 결과

- cleanup 실행 여부: True
- JSONL record 수: 50
- id 고유 수: 50
- Excel all_gold 행 수: 50
- readable CSV 행 수: 50
- secret 의심 패턴: []
- 긴 evidence 의심 id: []

## 6. 최종 남은 Phase 3 핵심 파일

- `eval/evaluation/data/rfp_domain_gold_sample.jsonl`
- `eval/evaluation/data/rfp_domain_gold_sample.xlsx`
- `eval/evaluation/data/rfp_domain_gold_sample_readable.csv`
- `eval/evaluation/data/rfp_domain_gold_sample_validation.csv`
- `eval/evaluation/data/rfp_domain_gold_hybrid_50_approved.csv`
- `eval/evaluation/docs/rfp_domain_gold_sample_guide.md`
- `eval/evaluation/docs/phase3_gold_jsonl_generation_report.md`
- `eval/evaluation/scripts/build_phase3_gold_sample_jsonl.py`

## 7. 주의사항

평가 실행에 필요한 `run_evaluation.py`, `src`, `tests`, `README.md`, `AGENTS.md`는 삭제하지 않는다.