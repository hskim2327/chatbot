from typing import Any


class DocumentDiversityRetriever:
    """Select final contexts from diverse source documents."""

    def __init__(
        self,
        base_retriever,
        candidate_k: int = 50,
        key: str = "doc_id",
        fill_remainder: bool = True,
    ):
        self.base_retriever = base_retriever
        self.candidate_k = candidate_k
        self.key = key
        self.fill_remainder = fill_remainder

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

        selected: list[dict[str, Any]] = []
        remainder: list[dict[str, Any]] = []
        seen: set[str] = set()

        for rank, item in enumerate(candidates, 1):
            copied = item.copy()
            group_key = _document_key(copied, self.key)
            copied["diversity_rank_before"] = rank
            copied["diversity_group_key"] = group_key

            if group_key and group_key not in seen:
                seen.add(group_key)
                selected.append(copied)
            else:
                remainder.append(copied)

            if len(selected) >= top_k:
                break

        if self.fill_remainder and len(selected) < top_k:
            for item in remainder:
                selected.append(item)
                if len(selected) >= top_k:
                    break

        for rank, item in enumerate(selected, 1):
            item["diversity_rank"] = rank
        return selected[:top_k]


def _document_key(item: dict[str, Any], key: str) -> str:
    metadata = item.get("metadata") or {}

    if key == "source_file":
        value = metadata.get("source_file") or item.get("doc_id") or metadata.get("doc_id")
    else:
        value = item.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file")

    if value in (None, ""):
        value = item.get("chunk_id") or metadata.get("chunk_id")
    return str(value or "")
