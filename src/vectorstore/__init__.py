from .faiss_store import FAISSVectorStore

__all__ = ["FAISSVectorStore", "ChromaVectorStore"]


def __getattr__(name: str):
    if name == "ChromaVectorStore":
        from .chroma_store import ChromaVectorStore

        return ChromaVectorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
