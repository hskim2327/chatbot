import re
from typing import Literal

from rank_bm25 import BM25Okapi

from src.retriever.metadata_filter import matches_metadata


BM25Tokenizer = Literal["regex", "whitespace"]
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")


class BM25Retriever:
    def __init__(self, chunks, tokenizer: BM25Tokenizer = "regex"):
        self.chunks = chunks
        self.tokenizer = tokenizer
        self.tokenized_corpus = [
            self._tokenize(chunk.get("text", ""))
            for chunk in chunks
        ]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query, top_k=5, metadata_filter=None):
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True
        )

        results = []
        for corpus_rank, (idx, score) in enumerate(ranked, 1):
            item = self.chunks[idx].copy()
            if not matches_metadata(item, metadata_filter):
                continue
            item["score"] = float(score)
            item["bm25_score"] = float(score)
            item["bm25_rank"] = corpus_rank
            results.append(item)
            if len(results) >= top_k:
                break

        return results

    def _tokenize(self, text: str) -> list[str]:
        if self.tokenizer == "whitespace":
            return [token.casefold() for token in str(text).split() if token]
        if self.tokenizer != "regex":
            raise ValueError(f"Unsupported BM25 tokenizer: {self.tokenizer}")
        return [
            token.casefold()
            for token in TOKEN_PATTERN.findall(str(text))
            if len(token) >= 2
        ]
