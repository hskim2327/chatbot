from __future__ import annotations

from typing import Any, Literal


DocumentScoreMethod = Literal["max", "mean_top_n", "sum_top_n"]


class DocumentScoreRetriever:
    """Aggregate chunk candidates into document-level retrieval results."""

    def __init__(
        self,
        base_retriever,
        candidate_k: int = 100,
        method: DocumentScoreMethod = "mean_top_n",
        top_n: int = 3,
        key: str = "doc_id",
    ):
        self.base_retriever = base_retriever
        self.candidate_k = candidate_k
        self.method = method
        self.top_n = top_n
        self.key = key

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        candidates = self.base_retriever.retrieve(
            query,
            top_k=max(top_k, self.candidate_k),
            metadata_filter=metadata_filter,
        )

        groups: dict[str, list[dict[str, Any]]] = {}
        for rank, item in enumerate(candidates, 1):
            copied = item.copy()
            copied["doc_score_rank_before"] = rank
            group_key = _document_key(copied, self.key)
            if not group_key:
                group_key = str(copied.get("chunk_id") or rank)
            copied["doc_score_group_key"] = group_key
            groups.setdefault(group_key, []).append(copied)

        scored_docs = []
        for group_key, items in groups.items():
            ranked_items = sorted(items, key=lambda item: float(item.get("score") or 0.0), reverse=True)
            scores = [float(item.get("score") or 0.0) for item in ranked_items]
            selected_scores = scores[: max(1, self.top_n)]
            doc_score = _aggregate_scores(selected_scores, self.method)

            representative = ranked_items[0].copy()
            representative["score"] = doc_score
            representative["doc_score"] = doc_score
            representative["doc_score_method"] = self.method
            representative["doc_score_top_n"] = self.top_n
            representative["doc_score_candidate_count"] = len(items)
            representative["doc_score_best_chunk_score"] = scores[0] if scores else 0.0
            representative["doc_score_group_key"] = group_key
            scored_docs.append(representative)

        scored_docs.sort(key=lambda item: float(item.get("doc_score") or item.get("score") or 0.0), reverse=True)
        for rank, item in enumerate(scored_docs, 1):
            item["doc_score_rank"] = rank
        return scored_docs[:top_k]


def _aggregate_scores(scores: list[float], method: DocumentScoreMethod) -> float:
    if not scores:
        return 0.0
    if method == "max":
        return max(scores)
    if method == "mean_top_n":
        return sum(scores) / len(scores)
    if method == "sum_top_n":
        return sum(scores)
    raise ValueError(f"Unsupported document score method: {method}")


def _document_key(item: dict[str, Any], key: str) -> str:
    metadata = item.get("metadata") or {}
    if key == "source_file":
        value = metadata.get("source_file") or item.get("doc_id") or metadata.get("doc_id")
    else:
        value = item.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file")
    if value in (None, ""):
        value = item.get("chunk_id") or metadata.get("chunk_id")
    return str(value or "")
