from typing import Any


class MultiQueryRetriever:
    """Run multiple query variants and combine results with reciprocal-rank fusion."""

    def __init__(self, base_retriever, query_expander, fetch_k: int = 20, rrf_k: int = 60):
        self.base_retriever = base_retriever
        self.query_expander = query_expander
        self.fetch_k = fetch_k
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        queries = self.query_expander.expand(query)
        combined: dict[str, dict[str, Any]] = {}

        for query_idx, expanded_query in enumerate(queries, 1):
            results = self.base_retriever.retrieve(
                expanded_query,
                top_k=max(top_k, self.fetch_k),
                metadata_filter=metadata_filter,
            )
            for rank, result in enumerate(results, 1):
                key = _result_key(result, fallback=f"{rank}:{query_idx}")
                if key not in combined:
                    combined[key] = result.copy()
                    combined[key]["score"] = 0.0
                item = combined[key]
                item["score"] += 1.0 / (self.rrf_k + rank)
                item.setdefault("matched_queries", [])
                item["matched_queries"].append(expanded_query)

        ranked = sorted(combined.values(), key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]


def _result_key(result: dict[str, Any], fallback: str) -> str:
    metadata = result.get("metadata") or {}
    doc_id = result.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file")
    chunk_id = result.get("chunk_id") or metadata.get("chunk_id")
    if doc_id is not None and chunk_id is not None:
        return f"{doc_id}:{chunk_id}"
    if chunk_id is not None:
        return f"chunk:{chunk_id}"
    return f"{doc_id or 'unknown'}:{fallback}"
