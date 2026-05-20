from pathlib import Path
from typing import Any, List

from src.embeddings import Embedder, OpenAIEmbedder
from src.retriever.metadata_filter import matches_metadata
from src.vectorstore.faiss_store import FAISSVectorStore


class DenseRetriever:
    """Dense retriever backed by an embedder and a vector store."""

    def __init__(
        self,
        chunks: List[dict[str, Any]] | None = None,
        embedder: Embedder | None = None,
        vector_store: FAISSVectorStore | None = None,
    ):
        self.chunks = chunks or []
        self.embedder = embedder or OpenAIEmbedder()
        self.vector_store = vector_store or FAISSVectorStore()

    def build_index(self, batch_size: int = 100) -> None:
        if not self.chunks:
            raise ValueError("Cannot build dense index without chunks.")

        texts = [chunk["text"] for chunk in self.chunks]
        embeddings = self.embedder.embed_texts(texts, batch_size=batch_size)
        self.vector_store.build(embeddings, self.chunks)

    def save(self, index_dir: str | Path) -> None:
        self.vector_store.save(index_dir)

    @classmethod
    def from_index(
        cls,
        index_dir: str | Path,
        embedder: Embedder | None = None,
    ) -> "DenseRetriever":
        vector_store = FAISSVectorStore.load(index_dir)
        return cls(
            chunks=vector_store.chunks,
            embedder=embedder or OpenAIEmbedder(),
            vector_store=vector_store,
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        fetch_k: int | None = None,
    ) -> List[dict[str, Any]]:
        query_embedding = self.embedder.embed_query(query)
        if not metadata_filter:
            candidates = self.vector_store.search(query_embedding, top_k=top_k)
            return self._annotate_dense_results(candidates)

        results: List[dict[str, Any]] = []
        search_k = max(fetch_k or top_k * 10, top_k)
        max_k = self._count_vectors() or search_k
        if self.vector_store.__class__.__name__ == "ChromaVectorStore":
            max_k = min(max_k, max(search_k, 25))

        while search_k <= max_k:
            candidates = self.vector_store.search(query_embedding, top_k=search_k)
            results = []
            for dense_rank, item in enumerate(candidates, 1):
                if matches_metadata(item, metadata_filter):
                    item["dense_rank"] = dense_rank
                    item["dense_score"] = item.get("score")
                    results.append(item)
            if len(results) >= top_k or search_k == max_k:
                break
            search_k = min(search_k * 2, max_k)

        return results[:top_k]

    def _count_vectors(self) -> int:
        if hasattr(self.vector_store, "count"):
            return int(self.vector_store.count())
        return len(getattr(self.vector_store, "chunks", []) or self.chunks or [])

    @staticmethod
    def _annotate_dense_results(results: List[dict[str, Any]]) -> List[dict[str, Any]]:
        for dense_rank, item in enumerate(results, 1):
            item["dense_rank"] = dense_rank
            item["dense_score"] = item.get("score")
        return results
