from typing import Any


class HybridRetriever:
    """Combine BM25 and dense retrieval with reciprocal-rank fusion."""

    def __init__(
        self,
        bm25_retriever,
        dense_retriever,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        rrf_k: int = 60,
        fetch_k: int = 50,
    ):
        self.bm25_retriever = bm25_retriever
        self.dense_retriever = dense_retriever
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.rrf_k = rrf_k
        self.fetch_k = fetch_k

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        candidate_k = max(top_k, self.fetch_k)
        bm25_results = self.bm25_retriever.retrieve(
            query,
            top_k=candidate_k,
            metadata_filter=metadata_filter,
        )
        dense_results = self.dense_retriever.retrieve(
            query,
            top_k=candidate_k,
            metadata_filter=metadata_filter,
            fetch_k=max(candidate_k * 10, 100),
        )

        combined: dict[str, dict[str, Any]] = {}
        self._add_ranked_results(combined, bm25_results, "bm25", self.bm25_weight)
        self._add_ranked_results(combined, dense_results, "dense", self.dense_weight)

        ranked = sorted(
            combined.values(),
            key=lambda item: item["score"],
            reverse=True,
        )
        return ranked[:top_k]

    def _add_ranked_results(
        self,
        combined: dict[str, dict[str, Any]],
        results: list[dict[str, Any]],
        source: str,
        weight: float,
    ) -> None:
        for rank, result in enumerate(results, 1):
            key = str(result.get("chunk_id") or f"{result.get('doc_id')}:{rank}:{source}")
            item = combined.setdefault(key, result.copy())
            item.setdefault("score", 0.0)
            item["score"] += weight / (self.rrf_k + rank)
            item[f"{source}_rank"] = rank
            item[f"{source}_score"] = result.get("score")
