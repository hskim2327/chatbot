from __future__ import annotations

import re
from typing import Any, Literal


SelectionStrategy = Literal["round_robin", "rrf"]

_SPLIT_BEFORE_PATTERNS = re.compile(
    r"(이렇게|다음으로|아울러|덧붙여|추가로|그리고\s+이|먼저|전체를|전체|종합|통합|합산|결산|네\s*곳|4\s*곳|4\s*개)",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_NOISE_PREFIX = re.compile(r"^[\s\-•*0-9.)①-⑳]+")


class LocalQueryDecomposer:
    """Heuristic decomposer for Korean multi-document RFP questions."""

    def __init__(self, max_queries: int = 8, include_original: bool = True):
        self.max_queries = max_queries
        self.include_original = include_original

    def expand(self, query: str) -> list[str]:
        query = str(query or "").strip()
        subqueries = self._extract_list_items(query)
        queries: list[str] = []
        for subquery in subqueries:
            if subquery and subquery not in queries:
                queries.append(subquery)
            if len(queries) >= self.max_queries:
                break

        if self.include_original and query and query not in queries:
            queries.append(query)

        return queries[: self.max_queries] or [query]

    def _extract_list_items(self, query: str) -> list[str]:
        lead = _SPLIT_BEFORE_PATTERNS.split(query, maxsplit=1)[0]
        lead = lead.replace("，", ",").replace("、", ",").replace(";", ",")
        raw_parts = [part.strip() for part in lead.split(",")]

        items: list[str] = []
        for part in raw_parts:
            cleaned = _clean_subquery(part)
            if _looks_like_subquery(cleaned):
                items.append(cleaned)

        if len(items) <= 1:
            return []
        return items


class QueryDecompositionRetriever:
    """Search decomposed sub-queries and merge results with document coverage in mind."""

    def __init__(
        self,
        base_retriever,
        decomposer: LocalQueryDecomposer | None = None,
        per_query_k: int = 20,
        selection: SelectionStrategy = "round_robin",
        ignore_metadata_filter: bool = False,
        rrf_k: int = 60,
    ):
        self.base_retriever = base_retriever
        self.decomposer = decomposer or LocalQueryDecomposer()
        self.per_query_k = per_query_k
        self.selection = selection
        self.ignore_metadata_filter = ignore_metadata_filter
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        queries = self.decomposer.expand(query)
        active_filter = None if self.ignore_metadata_filter else metadata_filter
        per_query_results: list[list[dict[str, Any]]] = []
        doc_items: dict[str, dict[str, Any]] = {}

        for query_idx, subquery in enumerate(queries, 1):
            results = self.base_retriever.retrieve(
                subquery,
                top_k=self.per_query_k,
                metadata_filter=active_filter,
            )
            annotated_results: list[dict[str, Any]] = []
            for rank, result in enumerate(results, 1):
                item = result.copy()
                doc_key = _document_key(item)
                item["decomposition_query"] = subquery
                item["decomposition_query_index"] = query_idx
                item["decomposition_query_rank"] = rank
                item["decomposition_doc_key"] = doc_key
                item_score = float(item.get("score") or 0.0)
                rrf_score = 1.0 / (self.rrf_k + rank)

                current = doc_items.get(doc_key)
                if current is None:
                    representative = item.copy()
                    representative["decomposition_score"] = rrf_score
                    representative["decomposition_best_chunk_score"] = item_score
                    representative["matched_queries"] = [subquery]
                    representative["decomposition_matched_query_count"] = 1
                    doc_items[doc_key] = representative
                else:
                    current["decomposition_score"] = float(current.get("decomposition_score") or 0.0) + rrf_score
                    current.setdefault("matched_queries", [])
                    if subquery not in current["matched_queries"]:
                        current["matched_queries"].append(subquery)
                    current["decomposition_matched_query_count"] = len(current["matched_queries"])
                    if item_score > float(current.get("decomposition_best_chunk_score") or 0.0):
                        keep_score = current["decomposition_score"]
                        keep_queries = current["matched_queries"]
                        keep_count = current["decomposition_matched_query_count"]
                        current.clear()
                        current.update(item.copy())
                        current["decomposition_score"] = keep_score
                        current["decomposition_best_chunk_score"] = item_score
                        current["matched_queries"] = keep_queries
                        current["decomposition_matched_query_count"] = keep_count

                annotated_results.append(item)
            per_query_results.append(annotated_results)

        if self.selection == "rrf":
            ranked = sorted(doc_items.values(), key=lambda item: float(item.get("decomposition_score") or 0.0), reverse=True)
        elif self.selection == "round_robin":
            ranked = self._round_robin(per_query_results, doc_items)
        else:
            raise ValueError(f"Unsupported query decomposition selection: {self.selection}")

        for rank, item in enumerate(ranked, 1):
            item["score"] = float(item.get("decomposition_score") or item.get("score") or 0.0)
            item["decomposition_rank"] = rank
            item["decomposition_query_count"] = len(queries)
        return ranked[:top_k]

    def _round_robin(
        self,
        per_query_results: list[list[dict[str, Any]]],
        doc_items: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_len = max((len(results) for results in per_query_results), default=0)

        for rank_idx in range(max_len):
            for results in per_query_results:
                if rank_idx >= len(results):
                    continue
                doc_key = results[rank_idx].get("decomposition_doc_key") or _document_key(results[rank_idx])
                if not doc_key or doc_key in seen:
                    continue
                seen.add(doc_key)
                selected.append(doc_items[doc_key])

        remainder = sorted(
            [item for key, item in doc_items.items() if key not in seen],
            key=lambda item: float(item.get("decomposition_score") or 0.0),
            reverse=True,
        )
        return selected + remainder


def _clean_subquery(text: str) -> str:
    text = _NOISE_PREFIX.sub("", str(text or "").strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(그리고|및|또한|아울러)\s+", "", text)
    return text.strip(" .,:;·/")


def _looks_like_subquery(text: str) -> bool:
    if len(text) < 6:
        return False
    tokens = _TOKEN_PATTERN.findall(text)
    if len(tokens) < 2:
        return False
    return any(re.search(r"[가-힣]", token) for token in tokens)


def _document_key(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    value = item.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file")
    if value in (None, ""):
        value = item.get("chunk_id") or metadata.get("chunk_id")
    return str(value or "")
