from typing import Sequence


class HuggingFaceEmbedder:
    """SentenceTransformers wrapper for local HuggingFace embedding models."""

    def __init__(
        self,
        model_name: str,
        query_prefix: str = "",
        document_prefix: str = "",
        batch_size: int = 32,
        normalize_embeddings: bool = False,
        device: str | None = None,
        max_seq_length: int | None = None,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "HuggingFace embedding models require optional dependencies. "
                "Install them with: .venv/bin/python -m pip install --no-cache-dir "
                "-r requirements-embeddings.txt"
            ) from error

        kwargs = {}
        if device:
            kwargs["device"] = device

        self.model = model_name
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.encoder = SentenceTransformer(model_name, **kwargs)
        if max_seq_length:
            self.encoder.max_seq_length = max_seq_length

    def embed_texts(self, texts: Sequence[str], batch_size: int = 100) -> list[list[float]]:
        return self._encode(texts, prefix=self.document_prefix, batch_size=batch_size)

    def embed_query(self, query: str) -> list[float]:
        return self._encode([query], prefix=self.query_prefix, batch_size=self.batch_size)[0]

    def _encode(self, texts: Sequence[str], prefix: str, batch_size: int) -> list[list[float]]:
        inputs = [f"{prefix}{text}" if text else f"{prefix} " for text in texts]
        embeddings = self.encoder.encode(
            inputs,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return embeddings.astype("float32").tolist()
