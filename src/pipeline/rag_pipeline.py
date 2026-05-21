from pathlib import Path
from typing import Any, Literal

from src.data import load_chunks_jsonl
from src.embeddings import EmbeddingConfig, create_embedder, default_index_dir, resolve_embedding_config
from src.generator import OpenAIGenerator
from src.retriever import BM25Retriever


RetrieverType = Literal["bm25", "dense", "hybrid"]
VectorStoreType = Literal["faiss", "chroma"]


class RAGPipeline:
    """End-to-end RAG pipeline for already-chunked RFP data."""

    def __init__(
        self,
        chunk_path: str = "data/processed/chunks_v2.jsonl",
        api_key: str | None = None,
        retriever_type: RetrieverType = "dense",
        top_k: int = 5,
        index_dir: str | None = None,
        embedding_preset: str = "openai-small",
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        generator_model: str = "gpt-5-mini",
        build_dense_index: bool = False,
        embedding_batch_size: int = 100,
        metadata_filter: dict[str, Any] | None = None,
        hybrid_fetch_k: int = 50,
        hybrid_bm25_weight: float = 0.5,
        hybrid_dense_weight: float = 0.5,
        bm25_tokenizer: str = "regex",
        vector_store_type: VectorStoreType = "faiss",
        chroma_collection: str = "rfp_chunks",
        multi_query: bool = False,
        multi_query_count: int = 3,
        multi_query_fetch_k: int = 20,
        query_decomposition: bool = False,
        decomposition_candidates_per_query: int = 20,
        decomposition_max_queries: int = 8,
        decomposition_selection: str = "round_robin",
        decomposition_ignore_metadata_filter: bool = False,
        decomposition_include_original: bool = True,
        decomposition_conditional: bool = False,
        decomposition_min_subqueries: int = 2,
        rerank: bool = False,
        rerank_candidates: int = 30,
        reranker_type: str = "keyword",
        rerank_after_diversity: bool = False,
        rerank_original_score_weight: float = 0.01,
        cross_encoder_model: str = "BAAI/bge-reranker-v2-m3",
        cross_encoder_batch_size: int = 32,
        cross_encoder_max_chars: int = 1200,
        document_diversity: bool = False,
        diversity_candidates: int = 50,
        diversity_key: str = "doc_id",
        document_scoring: bool = False,
        doc_score_candidates: int = 100,
        doc_score_method: str = "mean_top_n",
        doc_score_top_n: int = 3,
        doc_score_key: str = "doc_id",
        compress_context: bool = False,
        compression_max_chars: int = 1200,
    ):
        self.chunk_path = chunk_path
        self.chunks = load_chunks_jsonl(chunk_path)
        self.retriever_type = retriever_type
        self.top_k = top_k
        self.vector_store_type = vector_store_type
        self.embedding_config: EmbeddingConfig = resolve_embedding_config(
            preset=embedding_preset,
            provider=embedding_provider,  # type: ignore[arg-type]
            model=embedding_model,
        )
        self.embedding_preset = self.embedding_config.preset
        self.embedding_provider = self.embedding_config.provider
        self.embedding_model = self.embedding_config.model
        self.index_dir = index_dir or default_index_dir(
            vector_store_type=vector_store_type,
            preset=embedding_preset,
            provider=embedding_provider,  # type: ignore[arg-type]
            model=embedding_model,
        )
        self.embedding_batch_size = embedding_batch_size
        self.metadata_filter = metadata_filter or {}
        self.hybrid_fetch_k = hybrid_fetch_k
        self.hybrid_bm25_weight = hybrid_bm25_weight
        self.hybrid_dense_weight = hybrid_dense_weight
        self.bm25_tokenizer = bm25_tokenizer
        self.chroma_collection = chroma_collection
        self.multi_query = multi_query
        self.multi_query_count = multi_query_count
        self.multi_query_fetch_k = multi_query_fetch_k
        self.query_decomposition = query_decomposition
        self.decomposition_candidates_per_query = decomposition_candidates_per_query
        self.decomposition_max_queries = decomposition_max_queries
        self.decomposition_selection = decomposition_selection
        self.decomposition_ignore_metadata_filter = decomposition_ignore_metadata_filter
        self.decomposition_include_original = decomposition_include_original
        self.decomposition_conditional = decomposition_conditional
        self.decomposition_min_subqueries = decomposition_min_subqueries
        self.rerank = rerank
        self.rerank_candidates = rerank_candidates
        self.reranker_type = reranker_type
        self.rerank_after_diversity = rerank_after_diversity
        self.rerank_original_score_weight = rerank_original_score_weight
        self.cross_encoder_model = cross_encoder_model
        self.cross_encoder_batch_size = cross_encoder_batch_size
        self.cross_encoder_max_chars = cross_encoder_max_chars
        self.document_diversity = document_diversity
        self.diversity_candidates = diversity_candidates
        self.diversity_key = diversity_key
        self.document_scoring = document_scoring
        self.doc_score_candidates = doc_score_candidates
        self.doc_score_method = doc_score_method
        self.doc_score_top_n = doc_score_top_n
        self.doc_score_key = doc_score_key
        self.compress_context = compress_context
        self.compression_max_chars = compression_max_chars
        self.api_key = api_key
        self.generator_model = generator_model
        self._generator: OpenAIGenerator | None = None
        self.retriever = self._create_retriever(build_dense_index=build_dense_index)

    def retrieve(self, query: str, metadata_filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.retriever.retrieve(
            query,
            top_k=self.top_k,
            metadata_filter=self._merge_metadata_filter(metadata_filter),
        )

    def generate_answer(self, query: str, retrieved: list[dict[str, Any]]) -> str:
        contexts = [self._format_context(item) for item in retrieved]
        return self.generator.generate(query, contexts)

    def _format_context(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata", {})

        return f"""
[문서 메타데이터]
문서ID: {item.get("doc_id")}
청크ID: {item.get("chunk_id")}
원본파일: {metadata.get("source_file") or "정보 없음"}
사업명: {metadata.get("project_name") or "정보 없음"}
발주기관: {metadata.get("issuer") or "정보 없음"}
예산: {self._format_budget(metadata.get("budget"))}
섹션: {metadata.get("section_path") or "정보 없음"}
금액표현: {metadata.get("amounts") or "정보 없음"}

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

    def run(
        self,
        query: str,
        generate: bool = True,
        metadata_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active_metadata_filter = self._merge_metadata_filter(metadata_filter)
        retrieved = self.retrieve(query, metadata_filter=metadata_filter)
        answer = self.generate_answer(query, retrieved) if generate else None

        return {
            "query": query,
            "retriever_type": self.retriever_type,
            "vector_store_type": self.vector_store_type,
            "embedding_preset": self.embedding_preset,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "metadata_filter": active_metadata_filter,
            "answer": answer,
            "retrieved": retrieved,
        }

    def _merge_metadata_filter(self, metadata_filter: dict[str, Any] | None = None) -> dict[str, Any]:
        if not metadata_filter:
            return dict(self.metadata_filter)
        return {**self.metadata_filter, **metadata_filter}

    def _create_retriever(self, build_dense_index: bool):
        if self.retriever_type == "bm25":
            retriever = BM25Retriever(self.chunks, tokenizer=self.bm25_tokenizer)
        elif self.retriever_type == "dense":
            retriever = self._create_dense_retriever(build_dense_index=build_dense_index)
        elif self.retriever_type == "hybrid":
            from src.retriever import HybridRetriever

            bm25_retriever = BM25Retriever(self.chunks, tokenizer=self.bm25_tokenizer)
            dense_retriever = self._create_dense_retriever(build_dense_index=build_dense_index)
            retriever = HybridRetriever(
                bm25_retriever=bm25_retriever,
                dense_retriever=dense_retriever,
                bm25_weight=self.hybrid_bm25_weight,
                dense_weight=self.hybrid_dense_weight,
                fetch_k=self.hybrid_fetch_k,
            )
        else:
            raise ValueError(f"Unsupported retriever_type: {self.retriever_type}")

        return self._wrap_retriever(retriever)

    def _wrap_retriever(self, retriever):
        if self.multi_query:
            from src.retriever import MultiQueryRetriever, OpenAIQueryExpander

            retriever = MultiQueryRetriever(
                base_retriever=retriever,
                query_expander=OpenAIQueryExpander(
                    api_key=self.api_key,
                    model=self.generator_model,
                    num_queries=self.multi_query_count,
                ),
                fetch_k=self.multi_query_fetch_k,
            )

        if self.query_decomposition:
            from src.retriever import LocalQueryDecomposer, QueryDecompositionRetriever

            retriever = QueryDecompositionRetriever(
                base_retriever=retriever,
                decomposer=LocalQueryDecomposer(
                    max_queries=self.decomposition_max_queries,
                    include_original=self.decomposition_include_original,
                ),
                per_query_k=self.decomposition_candidates_per_query,
                selection=self.decomposition_selection,
                ignore_metadata_filter=self.decomposition_ignore_metadata_filter,
                conditional=self.decomposition_conditional,
                min_subqueries=self.decomposition_min_subqueries,
            )

        if self.rerank and not self.rerank_after_diversity:
            retriever = self._create_rerank_wrapper(retriever)

        if self.document_scoring:
            from src.retriever import DocumentScoreRetriever

            retriever = DocumentScoreRetriever(
                base_retriever=retriever,
                candidate_k=self.doc_score_candidates,
                method=self.doc_score_method,
                top_n=self.doc_score_top_n,
                key=self.doc_score_key,
            )

        if self.document_diversity:
            from src.retriever import DocumentDiversityRetriever

            retriever = DocumentDiversityRetriever(
                base_retriever=retriever,
                candidate_k=self.diversity_candidates,
                key=self.diversity_key,
            )

        if self.rerank and self.rerank_after_diversity:
            retriever = self._create_rerank_wrapper(retriever)

        if self.compress_context:
            from src.retriever import ContextualCompressionRetriever, KeywordContextCompressor

            retriever = ContextualCompressionRetriever(
                base_retriever=retriever,
                compressor=KeywordContextCompressor(max_chars=self.compression_max_chars),
            )

        return retriever

    def _create_rerank_wrapper(self, retriever):
        from src.retriever import CrossEncoderReranker, RerankRetriever
        from src.retriever.rerank import KeywordReranker

        if self.reranker_type == "cross-encoder":
            reranker = CrossEncoderReranker(
                model_name=self.cross_encoder_model,
                batch_size=self.cross_encoder_batch_size,
                max_chars=self.cross_encoder_max_chars,
            )
        elif self.reranker_type == "keyword":
            reranker = KeywordReranker(original_score_weight=self.rerank_original_score_weight)
        else:
            raise ValueError(f"Unsupported reranker_type: {self.reranker_type}")

        return RerankRetriever(
            base_retriever=retriever,
            reranker=reranker,
            candidate_k=self.rerank_candidates,
        )

    def _create_dense_retriever(self, build_dense_index: bool):
        from src.retriever import DenseRetriever

        embedder = create_embedder(
            preset=self.embedding_preset,
            provider=self.embedding_provider,
            model=self.embedding_model,
            api_key=self.api_key,
            batch_size=self.embedding_batch_size,
        )
        vector_store = self._load_or_create_vector_store(build_dense_index=build_dense_index)

        if build_dense_index:
            retriever = DenseRetriever(chunks=self.chunks, embedder=embedder, vector_store=vector_store)
            retriever.build_index(batch_size=self.embedding_batch_size)
            retriever.save(self.index_dir)
            return retriever

        return DenseRetriever(chunks=getattr(vector_store, "chunks", []), embedder=embedder, vector_store=vector_store)

    def _load_or_create_vector_store(self, build_dense_index: bool):
        if self.vector_store_type == "faiss":
            from src.vectorstore import FAISSVectorStore

            index_path = Path(self.index_dir) / "index.faiss"
            if build_dense_index:
                return FAISSVectorStore()
            if not index_path.exists():
                raise FileNotFoundError(
                    f"Dense index not found at {index_path}. "
                    "Run scripts/build_vector_index.py first or pass build_dense_index=True."
                )
            return FAISSVectorStore.load(self.index_dir)

        if self.vector_store_type == "chroma":
            from src.vectorstore import ChromaVectorStore

            return ChromaVectorStore.load(self.index_dir, collection_name=self.chroma_collection)

        raise ValueError(f"Unsupported vector_store_type: {self.vector_store_type}")
