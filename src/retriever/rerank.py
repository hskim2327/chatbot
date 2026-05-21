import re
from typing import Any


class KeywordReranker:
    """Lightweight local reranker based on query term overlap and metadata matches."""

    def __init__(self, original_score_weight: float = 0.01):
        self.original_score_weight = original_score_weight

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
            rerank_score = coverage + (original_score * self.original_score_weight)

            copied = item.copy()
            copied["rerank_rank_before"] = idx
            copied["rerank_score"] = rerank_score
            reranked.append(copied)

        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        for rank, item in enumerate(reranked, 1):
            item["rerank_rank"] = rank
        return reranked


class CrossEncoderReranker:
    """Reranker that scores query-document pairs with a sentence-transformers CrossEncoder."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        batch_size: int = 32,
        max_chars: int = 1200,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_chars = max_chars
        self.device = device
        self._model = None

    def rerank(self, query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return items

        pairs = [(query, self._format_item(item)) for item in items]
        scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )

        reranked = []
        for idx, (item, score) in enumerate(zip(items, scores), 1):
            copied = item.copy()
            copied["rerank_rank_before"] = idx
            copied["rerank_score"] = float(score)
            copied["reranker_model"] = self.model_name
            reranked.append(copied)

        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        for rank, item in enumerate(reranked, 1):
            item["rerank_rank"] = rank
        return reranked

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            kwargs = {"device": self.device} if self.device else {}
            self._model = CrossEncoder(self.model_name, **kwargs)
        return self._model

    def _format_item(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        parts = [
            metadata.get("source_file"),
            metadata.get("project_name"),
            metadata.get("issuer"),
            item.get("text"),
        ]
        text = "\n".join(str(part) for part in parts if part)
        return text[: self.max_chars] if self.max_chars and self.max_chars > 0 else text


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
