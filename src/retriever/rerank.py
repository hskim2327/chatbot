import re
from typing import Any


class KeywordReranker:
    """Lightweight local reranker based on query term overlap and metadata matches."""

    def rerank(self, query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_terms = set(_tokenize(query))
        if not query_terms:
            return items

        reranked = []
        for idx, item in enumerate(items, 1):
            text = item.get("text", "")
            metadata = item.get("metadata", {})
            haystack = " ".join(
                str(value)
                for value in [
                    text,
                    metadata.get("project_name"),
                    metadata.get("issuer"),
                    metadata.get("source_file"),
                    metadata.get("budget"),
                    metadata.get("amounts"),
                ]
                if value
            )
            item_terms = set(_tokenize(haystack))
            overlap = len(query_terms & item_terms)
            coverage = overlap / len(query_terms)
            original_score = float(item.get("score") or 0.0)
            rerank_score = coverage + (original_score * 0.01)

            copied = item.copy()
            copied["rerank_rank_before"] = idx
            copied["rerank_score"] = rerank_score
            reranked.append(copied)

        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        for rank, item in enumerate(reranked, 1):
            item["rerank_rank"] = rank
        return reranked


class RerankRetriever:
    def __init__(self, base_retriever, reranker: KeywordReranker | None = None, candidate_k: int = 30):
        self.base_retriever = base_retriever
        self.reranker = reranker or KeywordReranker()
        self.candidate_k = candidate_k

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
        return self.reranker.rerank(query, candidates)[:top_k]


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z가-힣]+", text.casefold()) if len(token) >= 2]
