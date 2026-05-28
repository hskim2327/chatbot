"""Phase 1 document-level retrieval metric 계산 모듈."""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from .config import OFFICIAL_TOP_K
from .normalization import doc_match_key, documents_match, extract_top_unique_documents, normalize_doc_id


def compute_retrieval_metrics(
    ground_truth_docs: list[str],
    retrieved_docs: list[str],
    top_k: int = OFFICIAL_TOP_K,
) -> dict[str, float]:
    """Hit@5, MRR@5, nDCG@5를 계산한다.

    이 프로젝트의 hit_at_5는 다중 정답 문서 질문을 반영하기 위해
    binary hit가 아니라 정답 문서 회수율로 계산한다.
    예: 정답 문서 2개 중 1개 검색 시 hit_at_5 = 0.5.
    """

    if not ground_truth_docs:
        return {"hit_at_5": math.nan, "mrr_at_5": math.nan, "ndcg_at_5": math.nan}

    gt_keys = {doc_match_key(doc) for doc in ground_truth_docs if doc_match_key(doc)}
    ranked_docs = [normalize_doc_id(doc) for doc in retrieved_docs[:top_k]]
    relevances = [
        1 if any(documents_match(gt_doc, doc) for gt_doc in ground_truth_docs) else 0
        for doc in ranked_docs
    ]

    matched_keys = _matched_ground_truth_keys(ground_truth_docs, ranked_docs)
    hit_at_5 = len(matched_keys) / len(gt_keys) if gt_keys else math.nan
    first_rank = next((idx + 1 for idx, rel in enumerate(relevances) if rel), None)
    mrr_at_5 = 1.0 / first_rank if first_rank is not None else 0.0

    dcg = sum(rel / math.log2(idx + 2) for idx, rel in enumerate(relevances))
    ideal_relevant_count = min(len(gt_keys), top_k)
    idcg = sum(1 / math.log2(idx + 2) for idx in range(ideal_relevant_count))
    ndcg_at_5 = dcg / idcg if idcg else math.nan

    return {"hit_at_5": hit_at_5, "mrr_at_5": mrr_at_5, "ndcg_at_5": ndcg_at_5}


def compute_doc_recall_metrics(
    ground_truth_docs: list[str],
    retrieved_docs: list[str],
    top_k: int = OFFICIAL_TOP_K,
) -> dict[str, float | int]:
    """정답 문서 중 몇 개를 top-k 문서에서 찾았는지 분석용 recall을 계산한다."""

    gt_keys = [doc_match_key(doc) for doc in ground_truth_docs if doc_match_key(doc)]
    unique_gt_keys = list(dict.fromkeys(gt_keys))
    ground_truth_doc_count = len(unique_gt_keys)
    if ground_truth_doc_count == 0:
        return {
            "ground_truth_doc_count": 0,
            "matched_doc_count": 0,
            "doc_recall_at_5": math.nan,
            "multi_doc_recall_at_5": math.nan,
            "all_docs_hit_at_5": math.nan,
        }

    ranked_docs = [normalize_doc_id(doc) for doc in retrieved_docs[:top_k]]
    matched_keys = _matched_ground_truth_keys(ground_truth_docs, ranked_docs)

    matched_doc_count = len(matched_keys)
    doc_recall_at_5 = matched_doc_count / ground_truth_doc_count
    return {
        "ground_truth_doc_count": ground_truth_doc_count,
        "matched_doc_count": matched_doc_count,
        "doc_recall_at_5": doc_recall_at_5,
        "multi_doc_recall_at_5": doc_recall_at_5 if ground_truth_doc_count > 1 else math.nan,
        "all_docs_hit_at_5": 1.0 if matched_doc_count == ground_truth_doc_count else 0.0,
    }


def _matched_ground_truth_keys(ground_truth_docs: list[str], ranked_docs: list[str]) -> set[str]:
    matched_keys: set[str] = set()
    for gt_doc in ground_truth_docs:
        gt_key = doc_match_key(gt_doc)
        if gt_key and any(documents_match(gt_doc, doc) for doc in ranked_docs):
            matched_keys.add(gt_key)
    return matched_keys


def first_relevant_rank(ground_truth_docs: list[str], retrieved_docs: list[str]) -> float:
    """가장 먼저 등장한 정답 문서의 rank를 반환한다."""

    if not ground_truth_docs:
        return math.nan
    for idx, doc in enumerate(retrieved_docs, start=1):
        if any(documents_match(gt_doc, doc) for gt_doc in ground_truth_docs):
            return float(idx)
    return math.nan


def evaluate_phase1(
    merged_df: pd.DataFrame,
    top_k: int = OFFICIAL_TOP_K,
    include_analysis_metrics: bool = False,
) -> pd.DataFrame:
    """eval과 prediction이 병합된 DataFrame에서 Phase 1 결과를 계산한다."""

    result_rows: list[dict[str, Any]] = []
    for _, row in merged_df.iterrows():
        gt_docs = row.get("ground_truth_doc_list") or []
        contexts = row.get("retrieved_contexts")
        retrieved_docs = extract_top_unique_documents(contexts, top_k=top_k)
        metrics = compute_retrieval_metrics(gt_docs, retrieved_docs, top_k=top_k)
        analysis_metrics = compute_doc_recall_metrics(gt_docs, retrieved_docs, top_k=top_k) if include_analysis_metrics else {}
        result_rows.append(
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "difficulty": row.get("difficulty"),
                **metrics,
                **analysis_metrics,
                "first_relevant_rank": first_relevant_rank(gt_docs, retrieved_docs),
                "retrieved_doc_ids": json.dumps(retrieved_docs, ensure_ascii=False),
                "ground_truth_docs": json.dumps(gt_docs, ensure_ascii=False),
                "prediction_missing": bool(row.get("prediction_missing", False)),
            }
        )
    return pd.DataFrame(result_rows)
