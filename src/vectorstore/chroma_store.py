import json
from pathlib import Path
from typing import Any, Iterable, List


class ChromaVectorStore:
    """Optional Chroma backend. Requires `chromadb` to be installed."""

    def __init__(
        self,
        persist_dir: str | Path = "indexes/chroma_openai",
        collection_name: str = "rfp_chunks",
    ):
        try:
            import chromadb
        except ImportError as error:
            raise ImportError("Install chromadb to use ChromaVectorStore: pip install chromadb") from error

        self.persist_dir = str(persist_dir)
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.chunks: List[dict[str, Any]] = []

    def build(self, embeddings: Iterable[Iterable[float]], chunks: List[dict[str, Any]]) -> None:
        self.chunks = list(chunks)
        ids = [str(chunk["chunk_id"]) for chunk in self.chunks]
        documents = [chunk.get("text", "") for chunk in self.chunks]
        metadatas = [{"_chunk_json": json.dumps(chunk, ensure_ascii=False)} for chunk in self.chunks]
        vectors = [list(vector) for vector in embeddings]

        batch_size = 1000
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=vectors[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

    def search(self, query_embedding: Iterable[float], top_k: int = 5) -> List[dict[str, Any]]:
        result = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=top_k,
            include=["metadatas", "distances", "documents"],
        )
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]

        items = []
        for metadata, distance, document in zip(metadatas, distances, documents):
            item = json.loads(metadata.get("_chunk_json", "{}")) if metadata else {}
            if not item:
                item = {"text": document, "metadata": {}}
            item = item.copy()
            item["score"] = float(1.0 / (1.0 + distance))
            items.append(item)
        return items

    def save(self, index_dir: str | Path | None = None) -> None:
        return None

    @classmethod
    def load(
        cls,
        index_dir: str | Path = "indexes/chroma_openai",
        collection_name: str = "rfp_chunks",
    ) -> "ChromaVectorStore":
        return cls(persist_dir=index_dir, collection_name=collection_name)

    def count(self) -> int:
        return self.collection.count()
