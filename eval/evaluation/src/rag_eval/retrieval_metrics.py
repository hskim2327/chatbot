"""Phase 1 document-level retrieval metric 계산 모듈."""

from __future__ import annotations

import math
import json
from typing import Any

import pandas as pd

from .config import OFFICIAL_TOP_K
from .normalization import extract_top_unique_documents, normalize_doc_id


def compute_retrieval_metrics(
    ground_truth_docs: list[str],
    retrieved_docs: list[str],
    top_k: int = OFFICIAL_TOP_K,
) -> dict[str, float]:
    """Hit@5, MRR@5, nDCG@5를 계산한다."""

    if not ground_truth_docs:
        return {"hit_at_5": math.nan, "mrr_at_5": math.nan, "ndcg_at_5": math.nan}

    gt_set = {normalize_doc_id(doc) for doc in ground_truth_docs if normalize_doc_id(doc)}
    ranked_docs = [normalize_doc_id(doc) for doc in retrieved_docs[:top_k]]
    relevances = [1 if doc in gt_set else 0 for doc in ranked_docs]

    hit_at_5 = 1.0 if any(relevances) else 0.0
    first_rank = next((idx + 1 for idx, rel in enumerate(relevances) if rel), None)
    mrr_at_5 = 1.0 / first_rank if first_rank is not None else 0.0

    dcg = sum(rel / math.log2(idx + 2) for idx, rel in enumerate(relevances))
    ideal_relevant_count = min(len(gt_set), top_k)
    idcg = sum(1 / math.log2(idx + 2) for idx in range(ideal_relevant_count))
    ndcg_at_5 = dcg / idcg if idcg else math.nan

    return {"hit_at_5": hit_at_5, "mrr_at_5": mrr_at_5, "ndcg_at_5": ndcg_at_5}


def first_relevant_rank(ground_truth_docs: list[str], retrieved_docs: list[str]) -> float:
    """가장 먼저 등장한 정답 문서의 rank를 반환한다."""

    if not ground_truth_docs:
        return math.nan
    gt_set = {normalize_doc_id(doc) for doc in ground_truth_docs if normalize_doc_id(doc)}
    for idx, doc in enumerate(retrieved_docs, start=1):
        if normalize_doc_id(doc) in gt_set:
            return float(idx)
    return math.nan


def evaluate_phase1(merged_df: pd.DataFrame, top_k: int = OFFICIAL_TOP_K) -> pd.DataFrame:
    """eval과 prediction이 병합된 DataFrame에서 Phase 1 결과를 계산한다."""

    result_rows: list[dict[str, Any]] = []
    for _, row in merged_df.iterrows():
        gt_docs = row.get("ground_truth_doc_list") or []
        contexts = row.get("retrieved_contexts")
        retrieved_docs = extract_top_unique_documents(contexts, top_k=top_k)
        metrics = compute_retrieval_metrics(gt_docs, retrieved_docs, top_k=top_k)
        result_rows.append(
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "difficulty": row.get("difficulty"),
                **metrics,
                "first_relevant_rank": first_relevant_rank(gt_docs, retrieved_docs),
                "retrieved_doc_ids": json.dumps(retrieved_docs, ensure_ascii=False),
                "ground_truth_docs": json.dumps(gt_docs, ensure_ascii=False),
                "prediction_missing": bool(row.get("prediction_missing", False)),
            }
        )
    return pd.DataFrame(result_rows)
