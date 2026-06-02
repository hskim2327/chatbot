# 평가 요약

최신 공식 평가는 `eval` 기준으로 실행했습니다.

결과 폴더:

```text
Phase1/Phase3 공식 산출물:
outputs/eval/new_eval_126_eval_schema_gold50_phase13_official/

RAGAS/Phase4 API 산출물:
outputs/eval/new_eval_126_full_ragas_phase34_openai_gold50/
```

## Phase1 Retrieval

| 지표 | 값 |
|---|---:|
| 평가 문항 수 | 50 |
| hit@5 | 1.000 |
| MRR@5 | 0.920 |
| nDCG@5 | 0.911 |

## Phase2 RAGAS

| 지표 | 값 |
|---|---:|
| faithfulness | 0.464 |
| answer_relevancy | 0.141 |
| context_precision | 0.056 |
| context_recall | 0.000 |
| error_count | 0 |

Phase2 결과 파일은 `ragas_summary.md`, `ragas_results.csv`입니다.

## Phase3 Domain

| 지표 | 값 |
|---|---:|
| 평가 문항 수 | 50 |
| 실패 문항 수 | 37 |
| phase3_task_score | 0.541 |
| budget_numeric_accuracy | 0.229 |
| required_field_accuracy | 0.600 |
| unanswerable_refusal_accuracy | 0.800 |
| multi_doc_structure_score | 0.578 |
| robust_query_consistency_score | 0.500 |

## Phase4 LLM Judge

| 항목 | 값 |
|---|---:|
| mode | api |
| model | gpt-4o-mini |
| reference_mode | evidence_only |
| 평가 입력 수 | 50 |
| 평가 완료 수 | 49 |
| 실패 수 | 1 |
| 종합 점수 | 69.1점 |
| 판정 | 제한적 참고 가능 |

## 해석

공식 Phase1 기준 정답 문서 포함률은 높게 나왔고, Phase4 judge 기준으로는 제한적 참고 가능 수준입니다. 다만 Phase3와 RAGAS를 보면 예산/금액 정확성, context precision, context recall이 낮아 개선 여지가 큽니다.

특히 현재 시스템의 핵심 병목은 “정답 문서 검색”보다 “질문에 직접 답하는 근거 evidence를 context에 넣는 것”입니다.
