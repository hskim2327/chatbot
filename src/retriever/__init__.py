from .bm25 import BM25Retriever

__all__ = ["BM25Retriever", "DenseRetriever"]


def __getattr__(name: str):
    if name == "DenseRetriever":
        from .dense import DenseRetriever

        return DenseRetriever
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
