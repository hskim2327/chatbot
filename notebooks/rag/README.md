# RAG 노트북

| 노트북 | 설명 |
|---|---|
| `embedding_retrieval_eval_p4_hwpx_125_quickcheck.ipynb` | P4 HWPX 125 corpus의 `chunks_v2_125.jsonl`을 Chroma에 적재하고 KoE5 retrieval 실험을 실행합니다. `RUN_MODE = "smoke"`, `"quick"`, `"exp100"`, `"full"`로 적재/평가 범위를 조절합니다. |

## 필수 입력

- `outputs/parsing_p4_hwpx_125/chunks_v2_125.jsonl`
- `outputs/parsing_p4_hwpx_125/pilot_docs_125.csv`
- `outputs/parsing_p4_hwpx_125/validation_report.json`
- `data/eval/*.csv`

## 실행 모드

- `smoke`: 앞쪽 청크 1,000개만 적재하고 질문 5개로 연결과 기본 동작을 확인합니다.
- `quick`: 전체 embed 대상 청크를 적재하고 질문 30개로 dense baseline을 빠르게 확인합니다.
- `exp100`: 전체 embed 대상 청크를 적재하고 100문항 고정 샘플로 6개 retrieval 조건을 비교합니다.
- `full`: 전체 embed 대상 청크를 적재하고 eligible eval 전체를 dense baseline으로 평가합니다.

## exp100 실험 조건

- `J0_dense_baseline`: KoE5 dense only baseline
- `J1_dense_wide`: dense 후보 수를 늘려 multi-doc 후보 누락 여부 확인
- `J2_bm25_only`: lexical/BM25 단독 검색
- `J3_dense_bm25_rrf`: dense + BM25 -> RRF, reranker 없음
- `J4_dense_rerank`: dense 후보 -> reranker
- `J5_hybrid_rrf_rerank`: dense + BM25 -> RRF -> reranker

## 주요 결과 파일

`RUN_MODE="exp100"` 기준 결과는 아래 폴더에 저장됩니다.

```text
outputs/retrieval_quickcheck_p4_hwpx_125/exp100/
```

주요 파일:

- `experiment_summary_exp100.csv`
- `all_experiment_results_exp100.csv`
- `all_experiment_contexts_exp100.jsonl`
- `failure_focus_*.csv`
- `predictions/*_predictions.jsonl`

## 지표 해석 기준

- `hit_at_5_any`, `mrr_at_5`, `ndcg_at_5`, `doc_recall_at_5`를 전체적으로 함께 봅니다.
- Single-doc은 `single_doc_mrr_at_5`를, multi-doc은 `multi_doc_ndcg_at_5`, `multi_doc_recall_at_5`, `partial_multi_doc_loss`를 별도로 해석합니다.
- `candidate_generation_failed_top10`을 엄격한 후보 생성 실패 지표로 사용합니다.
- `candidate_generation_failed_top30`은 너무 관대할 수 있으므로 참고 지표로만 사용합니다.

## 주의

- Chroma DB는 Colab에서는 Google Drive가 아니라 `/content/...` 같은 런타임 로컬 경로에 만드는 것을 권장합니다.
- 생성된 Chroma DB, embedding cache, quickcheck 결과 파일은 명시적으로 공유해야 하는 경우가 아니면 GitHub에 올리지 않습니다.
- 첫 셀에는 `chromadb/opentelemetry`, `sentence-transformers/transformers/tokenizers` 버전 충돌 방어 코드가 들어 있습니다.
