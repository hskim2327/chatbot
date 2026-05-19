from typing import Protocol, Sequence


class Embedder(Protocol):
    """Common interface used by dense retrievers."""

    model: str

    def embed_texts(self, texts: Sequence[str], batch_size: int = 100) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        ...
