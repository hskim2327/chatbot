from .bm25 import BM25Retriever

__all__ = [
    "BM25Retriever",
    "DenseRetriever",
    "HybridRetriever",
    "MultiQueryRetriever",
    "OpenAIQueryExpander",
    "RerankRetriever",
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
    if name == "ContextualCompressionRetriever":
        from .compression import ContextualCompressionRetriever

        return ContextualCompressionRetriever
    if name == "KeywordContextCompressor":
        from .compression import KeywordContextCompressor

        return KeywordContextCompressor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
