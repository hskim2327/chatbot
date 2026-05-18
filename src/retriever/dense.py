from pathlib import Path
from typing import Any, List

from src.embeddings.openai_embedder import OpenAIEmbedder
from src.vectorstore.faiss_store import FAISSVectorStore


class DenseRetriever:
    """Dense retriever backed by an embedder and a FAISS vector store."""

    def __init__(
        self,
        chunks: List[dict[str, Any]] | None = None,
        embedder: OpenAIEmbedder | None = None,
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
        embedder: OpenAIEmbedder | None = None,
    ) -> "DenseRetriever":
        vector_store = FAISSVectorStore.load(index_dir)
        return cls(
            chunks=vector_store.chunks,
            embedder=embedder or OpenAIEmbedder(),
            vector_store=vector_store,
        )

    def retrieve(self, query: str, top_k: int = 5) -> List[dict[str, Any]]:
        query_embedding = self.embedder.embed_query(query)
        return self.vector_store.search(query_embedding, top_k=top_k)
