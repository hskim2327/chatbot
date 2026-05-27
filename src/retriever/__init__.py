from .bm25 import BM25Retriever

__all__ = [
    "BM25Retriever",
    "DenseRetriever",
    "HybridRetriever",
    "MultiQueryRetriever",
    "OpenAIQueryExpander",
    "RerankRetriever",
    "CrossEncoderReranker",
    "DocumentDiversityRetriever",
    "DocumentScoreRetriever",
    "TargetAwareRetriever",
    "TargetQueryExtractor",
    "LocalQueryDecomposer",
    "QueryDecompositionRetriever",
    "ContextualCompressionRetriever",
    "KeywordContextCompressor",
]


def __getattr__(name: str):
    if name == "DenseRetriever":
        from .dense import DenseRetriever

        return DenseRetriever
    if name == "HybridRetriever":
        from .hybrid import HybridRetriever

        return HybridRetriever
    if name == "MultiQueryRetriever":
        from .multiquery import MultiQueryRetriever

        return MultiQueryRetriever
    if name == "OpenAIQueryExpander":
        from .query_expansion import OpenAIQueryExpander

        return OpenAIQueryExpander
    if name == "RerankRetriever":
        from .rerank import RerankRetriever

        return RerankRetriever
    if name == "CrossEncoderReranker":
        from .rerank import CrossEncoderReranker

        return CrossEncoderReranker
    if name == "DocumentDiversityRetriever":
        from .diversity import DocumentDiversityRetriever

        return DocumentDiversityRetriever
    if name == "DocumentScoreRetriever":
        from .document_score import DocumentScoreRetriever

        return DocumentScoreRetriever
    if name == "TargetAwareRetriever":
        from .target_aware import TargetAwareRetriever

        return TargetAwareRetriever
    if name == "TargetQueryExtractor":
        from .target_aware import TargetQueryExtractor

        return TargetQueryExtractor
    if name == "LocalQueryDecomposer":
        from .query_decomposition import LocalQueryDecomposer

        return LocalQueryDecomposer
    if name == "QueryDecompositionRetriever":
        from .query_decomposition import QueryDecompositionRetriever

        return QueryDecompositionRetriever
    if name == "ContextualCompressionRetriever":
        from .compression import ContextualCompressionRetriever

        return ContextualCompressionRetriever
    if name == "KeywordContextCompressor":
        from .compression import KeywordContextCompressor

        return KeywordContextCompressor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
