from dataclasses import dataclass, replace
import re
from typing import Literal

from .base import Embedder
from .openai_embedder import OpenAIEmbedder


EmbeddingProvider = Literal["openai", "huggingface"]


@dataclass(frozen=True)
class EmbeddingConfig:
    preset: str
    provider: EmbeddingProvider
    model: str
    index_name: str
    query_prefix: str = ""
    document_prefix: str = ""
    max_seq_length: int | None = None


EMBEDDING_PRESETS: dict[str, EmbeddingConfig] = {
    "openai-small": EmbeddingConfig(
        preset="openai-small",
        provider="openai",
        model="text-embedding-3-small",
        index_name="openai",
    ),
    "openai-large": EmbeddingConfig(
        preset="openai-large",
        provider="openai",
        model="text-embedding-3-large",
        index_name="openai_large",
    ),
    "bge-m3": EmbeddingConfig(
        preset="bge-m3",
        provider="huggingface",
        model="BAAI/bge-m3",
        index_name="bge_m3",
        max_seq_length=8192,
    ),
    "koe5": EmbeddingConfig(
        preset="koe5",
        provider="huggingface",
        model="nlpai-lab/KoE5",
        index_name="koe5",
        query_prefix="query: ",
        document_prefix="passage: ",
        max_seq_length=512,
    ),
    "kure": EmbeddingConfig(
        preset="kure",
        provider="huggingface",
        model="nlpai-lab/KURE-v1",
        index_name="kure_v1",
        max_seq_length=8192,
    ),
}


def embedding_preset_choices() -> list[str]:
    return sorted(EMBEDDING_PRESETS)


def resolve_embedding_config(
    preset: str = "openai-small",
    model: str | None = None,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingConfig:
    try:
        config = EMBEDDING_PRESETS[preset]
    except KeyError as error:
        choices = ", ".join(embedding_preset_choices())
        raise ValueError(f"Unsupported embedding preset: {preset}. Choose one of: {choices}") from error

    if provider is None and model and "/" in model:
        provider = "huggingface"

    if provider:
        config = replace(config, provider=provider)

    if model and model != config.model:
        config = replace(
            config,
            model=model,
            index_name=_custom_index_name(config.provider, model),
        )

    return config


def create_embedder(
    preset: str = "openai-small",
    model: str | None = None,
    provider: EmbeddingProvider | None = None,
    api_key: str | None = None,
    batch_size: int = 100,
) -> Embedder:
    config = resolve_embedding_config(preset=preset, model=model, provider=provider)

    if config.provider == "openai":
        return OpenAIEmbedder(api_key=api_key, model=config.model)

    if config.provider == "huggingface":
        from .huggingface_embedder import HuggingFaceEmbedder

        return HuggingFaceEmbedder(
            model_name=config.model,
            query_prefix=config.query_prefix,
            document_prefix=config.document_prefix,
            batch_size=batch_size,
            max_seq_length=config.max_seq_length,
        )

    raise ValueError(f"Unsupported embedding provider: {config.provider}")


def default_index_dir(
    vector_store_type: str,
    preset: str = "openai-small",
    model: str | None = None,
    provider: EmbeddingProvider | None = None,
) -> str:
    config = resolve_embedding_config(preset=preset, model=model, provider=provider)
    return f"indexes/{vector_store_type}_{config.index_name}"


def _custom_index_name(provider: EmbeddingProvider, model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")
    return f"{provider}_{slug}"
