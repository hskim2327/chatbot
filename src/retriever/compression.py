import re
from typing import Any


class KeywordContextCompressor:
    """Keep query-relevant text windows while preserving metadata."""

    def __init__(self, max_chars: int = 1200, window_chars: int = 220):
        self.max_chars = max_chars
        self.window_chars = window_chars

    def compress(self, query: str, item: dict[str, Any]) -> dict[str, Any]:
        text = item.get("text", "")
        if len(text) <= self.max_chars:
            copied = item.copy()
            copied["compression_ratio"] = 1.0
            return copied

        terms = [term for term in _tokenize(query) if len(term) >= 2]
        windows = []
        lower_text = text.casefold()

        for term in terms:
            start = 0
            term_lower = term.casefold()
            while True:
                idx = lower_text.find(term_lower, start)
                if idx == -1:
                    break
                left = max(0, idx - self.window_chars)
                right = min(len(text), idx + len(term) + self.window_chars)
                windows.append((left, right))
                start = idx + len(term)

        if not windows:
            compressed = text[:self.max_chars]
        else:
            compressed_parts = []
            for left, right in _merge_windows(windows):
                part = text[left:right].strip()
                if part:
                    compressed_parts.append(part)
                if sum(len(part) for part in compressed_parts) >= self.max_chars:
                    break
            compressed = "\n...\n".join(compressed_parts)[:self.max_chars]

        copied = item.copy()
        copied["original_text"] = text
        copied["text"] = compressed
        copied["compression_ratio"] = len(compressed) / len(text) if text else 1.0
        return copied


class ContextualCompressionRetriever:
    def __init__(self, base_retriever, compressor: KeywordContextCompressor | None = None):
        self.base_retriever = base_retriever
        self.compressor = compressor or KeywordContextCompressor()

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results = self.base_retriever.retrieve(query, top_k=top_k, metadata_filter=metadata_filter)
        return [self.compressor.compress(query, item) for item in results]


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z가-힣]+", text.casefold()) if token]


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    windows = sorted(windows)
    merged = [windows[0]]
    for left, right in windows[1:]:
        prev_left, prev_right = merged[-1]
        if left <= prev_right:
            merged[-1] = (prev_left, max(prev_right, right))
        else:
            merged.append((left, right))
    return merged
