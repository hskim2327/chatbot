# RAG Retrieval/Generation Experiment Log

이 문서는 지금까지 나온 주요 retrieval/generation 기법과 실험 결과를 한 곳에 모은 기록입니다. 기존 결과 파일은 그대로 두고, 해석과 비교만 정리했습니다.

## 1. 데이터와 평가 기준

- 최신 corpus: `data/processed/chunks_v2_690.jsonl`
- 최신 source store: `data/processed/source_store_v2_690.jsonl`
- 최신 vector DB: `indexes/chroma_kure_v1_chunks_v2_690`
- 최신 raw retrieval prediction: `outputs/predictions/104_best_dense_qdecomp_docscore_targetaware_kure_chroma_chunks_v2_690_phase34_gold50.jsonl`
- generation 평가용 gold 50문항: Phase 3/4 gold와 겹치는 50문항

주의할 점:
- raw retrieval 평가는 검색기가 가져온 원래 top 문서를 평가합니다.
- generation context 평가는 LLM에 실제로 넣은 `evidence_blocks`를 `retrieved_contexts`로 변환해 평가합니다.
- 따라서 raw retrieval 점수와 generation context 점수가 다를 수 있습니다.

## 2. Retrieval 쪽 주요 기법

| 기법 | 역할 | 결과 해석 |
|---|---|---|
| Dense retrieval | KURE embedding + Chroma 검색 | 최종 retrieval 기반으로 사용 |
| Query decomposition | 복합 질문을 여러 검색 query로 확장 | 다중 문서/복합 질문에서 후보 확보에 도움 |
| RRF merge | 여러 query 결과를 결합 | query decomposition 결과를 안정적으로 합침 |
| docscore mean3 | 문서 내 상위 chunk 점수 평균으로 문서 점수 계산 | chunk 하나에 과하게 끌리는 문제 완화 |
| target-aware reranking | 질문의 기관명/사업명 target과 맞는 문서 가중 | 유사 기관/유사 사업 distractor 감소 |
| relaxed filter | target이 완벽히 안 맞아도 일부 후보를 유지 | 오타/표기 차이에 강하게 만듦 |
| Chroma HNSW tuned | Chroma 기반 벡터 DB | 최신 DB 기준 최종 사용 |

## 3. Raw Retrieval 대표 결과

파일: `outputs/eval/final_690_retrieval_104_phase34_gold50/eval_summary.md`

| metric | score |
|---|---:|
| hit@5 | 0.9633 |
| MRR@5 | 0.9300 |
| nDCG@5 | 0.9215 |
| doc_recall@5 | 0.9633 |
| multi_doc_recall@5 | 0.9127 |

해석:
- 정답 문서 자체는 상당히 잘 찾는 상태입니다.
- 이후 성능 병목은 주로 “정답 문서를 찾았지만 generation context에 어떤 chunk/evidence를 넣을 것인가” 쪽으로 이동했습니다.

## 4. Generation context 쪽 주요 기법

| 기법 | 역할 | 상태 |
|---|---|---|
| `rfp_recommended` | 짧고 정돈된 RFP 전용 context | 실험 완료 |
| `rfp_target_evidence` | target 문서와 직접 답변 evidence 우선 | 기존 최종 generation 조합 |
| `rfp_budget_target_evidence` | 예산 질문에서 target/budget evidence 강화 | 실험 완료 |
| `rfp_preserve_top_evidence` | raw retrieval top 문서를 최대한 보존 | context coverage는 상승, 생성 점수는 소폭 하락 |
| source_store lookup | 문서 요약, 후보값, final/computed 값 보조 | generation에서 도움 되는 경우 있음 |
| 금액 정규화 | `1,515,000천원` 같은 값을 원문/환산값으로 함께 제공 | 적용됨 |
| 질문 유형별 답변 템플릿 | 예산/기간/다중문서 답변 형식을 강제 | `preserve_top` 계열부터 적용 |

## 5. 20문항 Context Sweep 결과

파일: `outputs/generation/context_sweep_690_20/context_sweep_690_20_summary.md`

| rank | variant | Phase3 | context hit@5 | context nDCG@5 |
|---:|---|---:|---:|---:|
| 1 | `rfp_preserve_top_evidence + source_store` | 0.2792 | 0.9583 | 0.9271 |
| 2 | `rfp_target_evidence + source_store` | 0.2542 | 0.8833 | 0.8658 |
| 3 | `rfp_recommended + source_store` | 0.2500 | 0.7833 | 0.7698 |
| 4 | `rfp_budget_target_evidence + source_store` | 0.2458 | 0.8833 | 0.8658 |

해석:
- 20문항에서는 raw top 문서 보존 방식이 가장 좋아 보였습니다.
- 다만 context가 길어지고 distractor 문서가 들어갈 위험이 있었습니다.

## 6. 50문항 확장 결과

파일: `outputs/generation/context_sweep_690_50/context_sweep_690_50_summary.md`

| variant | Phase3 | budget | required | unanswerable | multi_doc | context hit@5 | context nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 기존 최종 `rfp_target_evidence + source_store` | 0.3097 | 0.2083 | 0.1656 | 0.5500 | 0.3500 | 0.9000 | 0.8741 |
| 새 `rfp_preserve_top_evidence + source_store` | 0.3033 | 0.2083 | 0.1111 | 0.6000 | 0.3500 | 0.9633 | 0.9215 |

해석:
- `preserve_top`은 context hit/nDCG와 multi-doc recall을 크게 회복했습니다.
- 하지만 raw top 문서를 전부 보존하면서 distractor와 noisy evidence도 같이 늘어 required field 점수가 떨어졌습니다.
- 그래서 현재 최종 generation 조합은 기존 `rfp_target_evidence + source_store` 유지가 더 낫습니다.

## 7. 이번 추가 개선 방향

이제는 raw top 문서를 전부 보존하지 않고, 다음 조건을 만족하는 문서만 선택적으로 보존합니다.

- target slot과 매칭된 문서
- target match score가 충분히 높은 문서
- 질문 유형에 맞는 required fact를 가진 문서
- source_store의 final/computed 값이 있는 문서

새 실험 모드:

- `rfp_selective_top_evidence + source_store`

기대 효과:
- `preserve_top`의 context coverage 장점은 일부 유지합니다.
- distractor 문서 주입은 줄입니다.
- 문서별로 질문 유형에 맞는 evidence를 최소 1개씩 더 강하게 넣습니다.

## 8. 관련 파일

- 기존 최종 생성 리뷰: `outputs/generation/final_690_phase34_gold_qwen/rfp_target_evidence_source_store_qwen3_8b_4bit_50_review.md`
- 기존 최종 OpenAI Judge 평가: `outputs/eval/final_690_phase34_gold_qwen_openai_judge/`
- 20문항 sweep: `outputs/generation/context_sweep_690_20/`
- 50문항 preserve-top 확장: `outputs/generation/context_sweep_690_50/`

## 9. 추가 실험: `rfp_selective_top_evidence`

파일: `outputs/generation/context_selective_690_20/selective_top_evidence_summary_20.md`

이번에는 raw top 문서를 전부 보존하지 않고, target match와 required fact가 있는 문서만 선택적으로 보존하는 방식을 추가했습니다.

| variant | Phase3 | context hit@5 | context nDCG@5 |
|---|---:|---:|---:|
| `rfp_preserve_top_evidence + source_store` | 0.2792 | 0.9583 | 0.9271 |
| `rfp_target_evidence + source_store` | 0.2542 | 0.8833 | 0.8658 |
| `rfp_selective_top_evidence + source_store` | 0.2250 | 0.9583 | 0.8800 |

결론:
- selective 방식은 context hit@5는 높게 유지했지만 Phase3 생성 점수는 낮아졌습니다.
- 특히 budget/required field 계열에서 source_store/final_budget 후보가 오답 방향으로 강하게 들어가는 케이스가 있었습니다.
- 따라서 50문항 확장은 하지 않았고, 현재 최종 generation 조합은 여전히 기존 `rfp_target_evidence + source_store`가 더 안정적입니다.
- 향후 개선은 source_store final 값 자체를 더 검증하거나, gold/evidence 기준으로 source_store 후보 신뢰도를 점검한 뒤 진행하는 편이 좋습니다.

## 10. 추가 실험: `rfp_target_evidence_guarded_source`

파일: `outputs/generation/context_guarded_source_690_20/guarded_source_summary_20.md`

기존 최종 후보인 `rfp_target_evidence + source_store`를 유지하되, source_store의 예산 final 값을 더 엄격하게 쓰는 guard를 추가했습니다.

핵심 조건:
- source_store의 `final_budget`, `final_budget_krw`, G2B 예산값을 바로 믿지 않습니다.
- 원래 retrieved row 안에서 같은 금액이 확인될 때만 source_store 예산값을 project_budget 근거로 승격합니다.
- 확인되지 않은 경우 source_store의 예산 필드와 예산성 full_text를 context에서 제거합니다.

| variant | Phase3 | context hit@5 | context nDCG@5 |
|---|---:|---:|---:|
| `rfp_preserve_top_evidence + source_store` | 0.2792 | 0.9583 | 0.9271 |
| `rfp_target_evidence + source_store` | 0.2542 | 0.8833 | 0.8658 |
| `rfp_target_evidence_guarded_source + source_store` | 0.2542 | 0.8833 | 0.8309 |
| `rfp_selective_top_evidence + source_store` | 0.2250 | 0.9583 | 0.8800 |

결론:
- guarded source는 잘못된 source_store 예산값이 답을 강하게 끌고 가는 현상은 줄였습니다.
- 하지만 20문항 Phase3 점수는 기존 `rfp_target_evidence + source_store`와 같고, context nDCG는 낮아졌습니다.
- 따라서 최종 기본 조합으로 교체하지는 않고, 안전성 우선/진단용 모드로 남겨두는 것이 적절합니다.
- 현재 병목은 source_store를 어떻게 조합하느냐보다, source_store/sidecar의 final 값 자체가 gold와 충돌하는 데이터 품질 문제에 더 가깝습니다.

## 11. Probe 20 추가 개선: evidence 선택 후 generation 회복 실험

고정 20문항 probe에서 `budget_priority` evidence selection은 evidence recall은 크게 올렸지만, generation Phase3 점수는 오히려 내려갔습니다. 원인은 예산 evidence가 모든 질문에 과하게 들어가면서 제출서류/요건/일반 설명 질문에서 context가 좁아지거나 noisy해졌기 때문입니다.

이번 추가 실험은 다음 순서로 진행했습니다.

| run | 핵심 변경 | Phase3 mean@20 |
|---|---|---:|
| 104 | 기존 full 50 최종 후보에서 같은 20문항만 비교 | 0.3908 |
| 105 | `budget_priority` evidence selection 강제 | 0.2936 |
| 106 | 예산 질문은 evidence selection, 비예산 질문은 raw retrieval 보존 | 0.3625 |
| 107 | 비예산 질문 target slot 추출 보강 | 0.3917 |
| 108 | 비예산 질문에서 금액 정규화 evidence 노이즈 제거 | 0.3950 |
| 109 | `있습니까/있나요` 오분류 제거 + `마감 일정` deadline 분류 보강 | 0.3950 |

세부 해석:
- 105는 evidence recall 자체는 좋아졌지만 generation 점수는 하락했습니다. 문서/근거를 더 잘 넣는 것과 LLM이 답을 더 잘 쓰는 것은 별개의 문제였습니다.
- 107은 Q006, Q009, P3-SUB-010처럼 target 문서 식별이 약했던 문항을 일부 회복했습니다.
- 108은 제출서류 질문에 `[금액 정규화]` 문구가 끼어드는 문제를 막아 Q025와 P3-SUB-001을 회복했습니다.
- 109는 분류 안정화 목적의 코드 개선입니다. 이번 20문항 점수는 108과 같지만, 일반적인 `있습니까` 문장을 부정/자격요건 질문으로 오분류하는 위험을 줄였습니다.

현재 probe 기준 best:
- `rfp_target_evidence_guarded_source + source_store`
- 106 conditional retrieval prediction 사용
- 비예산 질문 amount normalization guard 적용
- Phase3 mean@20: **0.3950**

주의:
- 20문항 probe라 전체 50문항 최종 성능을 보장하지는 않습니다.
- 다음 확장은 108/109 계열을 50문항으로 돌려서 기존 104 full과 비교하는 것이 가장 자연스럽습니다.

## 12. 108/109 계열 30문항 확장 검증

20문항 probe에서 가장 좋았던 108/109 계열을 전체 입력 교집합 30문항으로 확장했습니다.

결과 파일:
- 생성 샘플: `outputs/generation/final_690_phase34_gold_qwen/110_best_amount_deadline_guard_qwen3_8b_4bit_50_samples.jsonl`
- 리뷰 파일: `outputs/generation/final_690_phase34_gold_qwen/110_best_amount_deadline_guard_qwen3_8b_4bit_50_review.md`
- 평가 결과: `outputs/eval/110_best_amount_deadline_guard_qwen3_8b_4bit_30_phase3/phase3_domain_results.csv`

같은 30문항 기준 비교:

| run | 설명 | Phase3 mean@30 |
|---|---|---:|
| 104 | 기존 full run 기준 | 0.2583 |
| 105 | evidence selection 강제 | 0.1769 |
| 110 | amount guard + deadline classifier + conditional evidence | 0.2500 |

변화 요약:
- 좋아진 문항: Q009 `0.000 -> 0.250`, Q034 일부 개선 케이스는 20문항 기준에서 확인됨.
- 나빠진 문항: Q006 `0.250 -> 0.000`, Q025 `0.500 -> 0.250`.
- 30문항 확장에서는 110이 104보다 낮아 최종 조합으로 교체하기에는 아직 부족합니다.

현재 판단:
- `amount normalization guard`와 `deadline classifier`는 코드 안정성 측면에서는 유지할 가치가 있습니다.
- 다만 conditional evidence prediction을 최종 retrieval/generation 입력으로 쓰는 것은 아직 불안정합니다.
- 최종 점수 기준으로는 기존 104 계열을 유지하고, 110은 실패 사례 분석용 후보로 두는 편이 좋습니다.

다음 개선 방향:
- Q034처럼 다중 문서 질문에서 source/evidence가 한 문서로 수렴하는 문제를 먼저 해결해야 합니다.
- Q006/Q025처럼 답을 했는데 평가 기준과 어긋나는 문항은 gold required field와 실제 질문 의도 간 충돌 여부를 별도 진단해야 합니다.

## 13. 111-115 개선 실험: task_family guidance와 진단용 라우팅

이번 실험은 기존 104 최종 후보 이후, Phase3 50문항에서 더 나은 조합을 찾기 위해 진행했습니다.

| run | 핵심 변경 | Phase3 mean@50 | 해석 |
|---|---|---:|---|
| 104 | 기존 최종 후보 | 0.3097 | 기준점 |
| 113 | guarded source context + 104 raw retrieval | 0.2886 | 예산 점수가 크게 하락 |
| 114 | guarded source context + 106 conditional retrieval | 0.3263 | 현재 가장 좋은 단일 조합 |
| 115 | required_fields는 104, 나머지는 114 사용 | 0.3363 | 진단용 라우팅. 실제 서비스에는 task classifier 필요 |

주요 해석:
- 114는 budget, unanswerable, 일부 submission 계열에서 104보다 좋아졌습니다.
- required_fields는 114에서 떨어졌고, 104 방식이 더 안정적이었습니다.
- 따라서 다음 개선은 `required_fields` 전용 context 구성 또는 질문 분류 기반 라우팅입니다.

주요 파일:
- `outputs/reports/generation_retrieval_improvement_summary_104_115.md`
- `outputs/generation/final_690_phase34_gold_qwen/114_stable_guarded_106conditional_qwen3_8b_4bit_50_review.md`
- `outputs/eval/114_stable_guarded_106conditional_qwen3_8b_4bit_50_phase3/phase3_domain_results.csv`
- `outputs/eval/115_task_family_routed_104_required_114_other_phase3/phase3_domain_results.csv`

## 14. 116-117: 질문 기반 auto route와 required_fields 전용 context

115 진단용 라우팅을 실제 서비스에서 쓸 수 있게, gold task_family가 아니라 질문 텍스트 기반 classifier로 옮기는 작업을 진행했습니다.

추가된 모드:
- `rfp_required_fields`: 원문 chunk/table/field keyword 중심 context
- `rfp_auto_route_104_114`: 질문이 required_fields로 보이면 104 스타일, 나머지는 114 guarded source 스타일

빠른 검증:

| run | 표본 | Phase3 mean | 해석 |
|---|---|---:|---|
| 116 | budget 10문항 | 0.1750 | 114와 동일. required_fields 효과 확인에는 부적절 |
| 117 | targeted 6문항 | 0.4139 | 104/114보다 높음. Q004, Q118 개선 |

주의:
- 117은 targeted 소규모 검증이므로 전체 최종 점수로 해석하면 안 됩니다.
- Q006/Q025/P3-SUB-001은 아직 회복하지 못해 별도 실패 분석이 필요합니다.

관련 리포트:
- `outputs/reports/generation_context_routing_service_summary_116_117.md`


## Generation Routing 118-121 Summary

자세한 내용은 `outputs/reports/generation_routing_improvement_118_121.md` 참고. 최종 고정 20문항 최고 조합은 `121_service_route_v2`, Phase3 mean=0.679167.

## 2026-05-30: Generation Routing Full-50 122/123

- 목표: 20문항에서 좋았던 classifier v2 + structured postprocess를 50문항 전체 기준으로 확장 확인.
- 방식: 114 full-50 결과를 기본으로 두고, required/submission 계열 19문항만 122로 재생성한 뒤 123 full-50 파일로 병합.
- 결과: 114 평균 `0.326333` -> 123 평균 `0.478333`.
- 좋아진 유형: `required_fields` 평균 `0.750000`, `unanswerable` 평균 `0.800000`.
- 남은 병목: `budget`, `multi_doc_comparison`, 일부 `submission_eligibility_deadline`.
- 상세 보고서: `outputs/reports/generation_routing_full50_122_123.md`
- 최종 후보 prediction: `outputs/generation/final_690_phase34_gold_qwen/123_service_route_classifier_v2_50_eval_predictions.jsonl`
- Phase 3 결과: `outputs/eval/123_service_route_classifier_v2_50_phase3/phase3_domain_results.csv`

## 2026-05-30: Generation Bottleneck 124-126

- 목표: 123 이후 남은 병목인 budget, multi-doc, submission을 좁게 실험.
- 새 mode: `rfp_service_route_v3`.
- 핵심 결과: 123 full-50 평균 `0.478333` -> 126 full-50 평균 `0.530556`.
- 가장 효과가 컸던 부분: multi-doc 평균 `0.350000` -> `0.577778`.
- submission은 `0.380952` -> `0.428571`로 소폭 개선.
- budget은 `0.229167`에 머물렀고, 일부 문항은 source_store/chunk 값과 gold 값 충돌이 있어 generation만으로 개선하기 어렵다.
- 최종 후보: `outputs/generation/final_690_phase34_gold_qwen/126_service_route_v3_nonbudget_patch_123_budget_50_eval_predictions.jsonl`
- 상세 보고서: `outputs/reports/generation_bottleneck_124_126.md`

