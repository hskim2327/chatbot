import json
from pathlib import Path
from typing import Any, Iterable, List

import faiss
import numpy as np


class FAISSVectorStore:
    """FAISS-backed vector store using cosine similarity by default."""

    INDEX_FILE = "index.faiss"
    CHUNKS_FILE = "chunks.json"
    CONFIG_FILE = "config.json"

    def __init__(self, dim: int | None = None, normalize: bool = True):
        self.dim = dim
        self.normalize = normalize
        self.index = faiss.IndexFlatIP(dim) if dim else None
        self.chunks: List[dict[str, Any]] = []

    def build(self, embeddings: Iterable[Iterable[float]], chunks: List[dict[str, Any]]) -> None:
        vectors = self._to_matrix(embeddings)
        if vectors.size == 0:
            raise ValueError("Cannot build FAISS index from empty embeddings.")

        if len(vectors) != len(chunks):
            raise ValueError(
                f"Embeddings/chunks length mismatch: {len(vectors)} embeddings, {len(chunks)} chunks."
            )

        self.dim = vectors.shape[1]
        self.index = faiss.IndexFlatIP(self.dim)
        self.chunks = list(chunks)

        if self.normalize:
            faiss.normalize_L2(vectors)

        self.index.add(vectors)

    def search(self, query_embedding: Iterable[float], top_k: int = 5) -> List[dict[str, Any]]:
        if self.index is None:
            raise ValueError("FAISS index is not initialized.")
        if not self.chunks:
            return []

        query = self._to_matrix([query_embedding])
        if query.shape[1] != self.dim:
            raise ValueError(f"Query dimension {query.shape[1]} does not match index dimension {self.dim}.")

        if self.normalize:
            faiss.normalize_L2(query)

        limit = min(top_k, len(self.chunks))
        scores, indices = self.index.search(query, limit)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            item = self.chunks[int(idx)].copy()
            item["score"] = float(score)
            results.append(item)

        return results

    def save(self, index_dir: str | Path) -> None:
        if self.index is None:
            raise ValueError("Cannot save an uninitialized FAISS index.")

        path = Path(index_dir)
        path.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self.index, str(path / self.INDEX_FILE))
        with open(path / self.CHUNKS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)
        with open(path / self.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"dim": self.dim, "normalize": self.normalize}, f, indent=2)

    @classmethod
    def load(cls, index_dir: str | Path) -> "FAISSVectorStore":
        path = Path(index_dir)

        with open(path / cls.CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        store = cls(dim=config["dim"], normalize=config.get("normalize", True))
        store.index = faiss.read_index(str(path / cls.INDEX_FILE))

        with open(path / cls.CHUNKS_FILE, "r", encoding="utf-8") as f:
            store.chunks = json.load(f)

        return store

    @staticmethod
    def _to_matrix(embeddings: Iterable[Iterable[float]]) -> np.ndarray:
        return np.asarray(list(embeddings), dtype="float32")
