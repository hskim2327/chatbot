from pathlib import Path
from typing import Any, Literal

from src.data import load_chunks_jsonl
from src.generator import OpenAIGenerator
from src.retriever import BM25Retriever


RetrieverType = Literal["bm25", "dense"]


class RAGPipeline:
    """End-to-end RAG pipeline for already-chunked RFP data."""

    def __init__(
        self,
        chunk_path: str = "data/processed/chunks_v2.jsonl",
        api_key: str | None = None,
        retriever_type: RetrieverType = "dense",
        top_k: int = 5,
        index_dir: str = "indexes/faiss_openai",
        embedding_model: str = "text-embedding-3-small",
        generator_model: str = "gpt-5-mini",
        build_dense_index: bool = False,
        embedding_batch_size: int = 100,
    ):
        self.chunk_path = chunk_path
        self.chunks = load_chunks_jsonl(chunk_path)
        self.retriever_type = retriever_type
        self.top_k = top_k
        self.index_dir = index_dir
        self.embedding_model = embedding_model
        self.embedding_batch_size = embedding_batch_size
        self.api_key = api_key
        self.generator_model = generator_model
        self._generator: OpenAIGenerator | None = None
        self.retriever = self._create_retriever(build_dense_index=build_dense_index)

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        return self.retriever.retrieve(query, top_k=self.top_k)

    def generate_answer(self, query: str, retrieved: list[dict[str, Any]]) -> str:
        contexts = [self._format_context(item) for item in retrieved]
        return self.generator.generate(query, contexts)

    def _format_context(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata", {})

        return f"""
[문서 메타데이터]
문서ID: {item.get("doc_id")}
청크ID: {item.get("chunk_id")}
사업명: {metadata.get("project_name") or "정보 없음"}
발주기관: {metadata.get("issuer") or "정보 없음"}
예산: {self._format_budget(metadata.get("budget"))}
섹션: {metadata.get("section_path") or "정보 없음"}

[본문]
{item.get("text", "")}
""".strip()

    @staticmethod
    def _format_budget(value: Any) -> str:
        if value in (None, ""):
            return "정보 없음"

        try:
            return f"{int(float(value)):,}원"
        except (TypeError, ValueError):
            return str(value)

    @property
    def generator(self) -> OpenAIGenerator:
        if self._generator is None:
            self._generator = OpenAIGenerator(api_key=self.api_key, model=self.generator_model)
        return self._generator

    def run(self, query: str, generate: bool = True) -> dict[str, Any]:
        retrieved = self.retrieve(query)
        answer = self.generate_answer(query, retrieved) if generate else None

        return {
            "query": query,
            "retriever_type": self.retriever_type,
            "answer": answer,
            "retrieved": retrieved,
        }

    def _create_retriever(self, build_dense_index: bool):
        if self.retriever_type == "bm25":
            return BM25Retriever(self.chunks)

        if self.retriever_type == "dense":
            from src.embeddings import OpenAIEmbedder
            from src.retriever import DenseRetriever

            embedder = OpenAIEmbedder(model=self.embedding_model)
            index_path = Path(self.index_dir) / "index.faiss"

            if build_dense_index:
                retriever = DenseRetriever(chunks=self.chunks, embedder=embedder)
                retriever.build_index(batch_size=self.embedding_batch_size)
                retriever.save(self.index_dir)
                return retriever

            if not index_path.exists():
                raise FileNotFoundError(
                    f"Dense index not found at {index_path}. "
                    "Run scripts/build_faiss_index.py first or pass build_dense_index=True."
                )

            return DenseRetriever.from_index(self.index_dir, embedder=embedder)

        raise ValueError(f"Unsupported retriever_type: {self.retriever_type}")
