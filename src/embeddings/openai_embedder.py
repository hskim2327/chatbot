import os
import time
from typing import Iterable, List, Sequence

from openai import OpenAI


class OpenAIEmbedder:
    """Small wrapper around OpenAI embedding models."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def embed_texts(self, texts: Sequence[str], batch_size: int = 100) -> List[List[float]]:
        embeddings: List[List[float]] = []

        for start in range(0, len(texts), batch_size):
            batch = list(texts[start:start + batch_size])
            embeddings.extend(self._embed_batch(batch))

        return embeddings

    def embed_query(self, query: str) -> List[float]:
        return self._embed_batch([query])[0]

    def _embed_batch(self, texts: Iterable[str]) -> List[List[float]]:
        batch = [text if text else " " for text in texts]
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                )
                return [item.embedding for item in response.data]
            except Exception as error:  # OpenAI SDK exposes several transient error types.
                last_error = error
                if attempt == self.max_retries - 1:
                    break
                time.sleep(self.retry_delay * (2 ** attempt))

        raise RuntimeError(f"OpenAI embedding failed after {self.max_retries} attempts") from last_error
