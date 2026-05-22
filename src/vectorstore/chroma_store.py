import json
from pathlib import Path
from typing import Any, Iterable, List

from src.retriever.metadata_filter import normalize_filter


class ChromaVectorStore:
    """Optional Chroma backend. Requires `chromadb` to be installed."""

    CHUNKS_FILE = "chunks.json"
    HNSW_CONFIG = {
        "hnsw": {
            "space": "cosine",
            "ef_search": 400,
            "ef_construction": 200,
            "max_neighbors": 32,
        }
    }

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
        self.persist_path = Path(persist_dir)
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self._get_or_create_collection()
        self.chunks: List[dict[str, Any]] = self._load_chunks_sidecar()
        self.supports_metadata_filter = True

    def build(self, embeddings: Iterable[Iterable[float]], chunks: List[dict[str, Any]]) -> None:
        self.chunks = list(chunks)
        self._reset_collection()
        self._save_chunks_sidecar()
        ids = [
            f"{chunk.get('doc_id') or 'doc'}:{chunk.get('chunk_id') or idx}:{idx}"
            for idx, chunk in enumerate(self.chunks)
        ]
        documents = [chunk.get("text", "") for chunk in self.chunks]
        metadatas = [self._metadata_for_chroma(idx, chunk) for idx, chunk in enumerate(self.chunks)]
        vectors = [[float(value) for value in vector] for vector in embeddings]

        batch_size = 1000
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=vectors[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

    def search(
        self,
        query_embedding: Iterable[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> List[dict[str, Any]]:
        query = {
            "query_embeddings": [[float(value) for value in query_embedding]],
            "n_results": top_k,
            "include": ["metadatas", "distances", "documents"],
        }
        where = self._where_filter(metadata_filter)
        if where:
            query["where"] = where

        try:
            result = self.collection.query(**query)
        except Exception:
            query.pop("where", None)
            result = self.collection.query(**query)

        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]

        items = []
        for metadata, distance, document in zip(metadatas, distances, documents):
            item = self._item_from_metadata(metadata, document)
            item = item.copy()
            item["score"] = float(1.0 / (1.0 + distance))
            items.append(item)
        return items

    def save(self, index_dir: str | Path | None = None) -> None:
        self._save_chunks_sidecar()

    @classmethod
    def load(
        cls,
        index_dir: str | Path = "indexes/chroma_openai",
        collection_name: str = "rfp_chunks",
    ) -> "ChromaVectorStore":
        return cls(persist_dir=index_dir, collection_name=collection_name)

    def count(self) -> int:
        return self.collection.count()

    def _reset_collection(self) -> None:
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        return self.client.get_or_create_collection(
            name=self.collection_name,
            configuration=self.HNSW_CONFIG,
            embedding_function=None,
        )

    def _load_chunks_sidecar(self) -> list[dict[str, Any]]:
        path = self.persist_path / self.CHUNKS_FILE
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_chunks_sidecar(self) -> None:
        self.persist_path.mkdir(parents=True, exist_ok=True)
        with (self.persist_path / self.CHUNKS_FILE).open("w", encoding="utf-8") as file:
            json.dump(self.chunks, file, ensure_ascii=False, indent=2)

    def _item_from_metadata(self, metadata: dict[str, Any] | None, document: str) -> dict[str, Any]:
        metadata = metadata or {}
        chunk_index = metadata.get("_chunk_index")
        if chunk_index is not None and self.chunks:
            index = int(chunk_index)
            if 0 <= index < len(self.chunks):
                return self.chunks[index]

        if "_chunk_json" in metadata:
            return json.loads(str(metadata.get("_chunk_json") or "{}"))
        return {"text": document, "metadata": dict(metadata)}

    @staticmethod
    def _metadata_for_chroma(idx: int, chunk: dict[str, Any]) -> dict[str, Any]:
        metadata = chunk.get("metadata") or {}
        chroma_metadata: dict[str, Any] = {"_chunk_index": idx}

        for key, value in {
            "doc_id": chunk.get("doc_id") or metadata.get("doc_id"),
            "chunk_id": chunk.get("chunk_id") or metadata.get("chunk_id"),
            "source_file": metadata.get("source_file"),
            "project_name": metadata.get("project_name"),
            "issuer": metadata.get("issuer"),
            "section_path": metadata.get("section_path"),
            "section_type": metadata.get("section_type"),
            "doc_key": metadata.get("doc_key"),
            "source_format": metadata.get("source_format"),
            "file_type": metadata.get("file_type"),
        }.items():
            if value not in (None, ""):
                chroma_metadata[key] = str(value)

        return chroma_metadata

    @staticmethod
    def _where_filter(metadata_filter: dict[str, Any] | None) -> dict[str, Any] | None:
        filters = normalize_filter(metadata_filter)
        if not filters:
            return None

        clauses = []
        for key, expected in filters.items():
            if key not in {"doc_id", "chunk_id", "source_file", "project_name", "issuer"}:
                continue
            values = ChromaVectorStore._filter_values(expected)
            if not values:
                continue
            if len(values) == 1:
                clauses.append({key: {"$eq": values[0]}})
            else:
                clauses.append({key: {"$in": values}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    @staticmethod
    def _filter_values(value: Any) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            values = [str(item) for item in value if item not in (None, "")]
        elif value in (None, ""):
            values = []
        else:
            values = [str(value)]
        return values
