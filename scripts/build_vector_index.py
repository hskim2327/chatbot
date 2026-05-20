import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.embeddings import default_index_dir, embedding_preset_choices, resolve_embedding_config
from src.pipeline import RAGPipeline


def resolve_index_dir(args: argparse.Namespace) -> None:
    args.embedding_config = resolve_embedding_config(
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
    )
    args.embedding_provider = args.embedding_config.provider
    args.embedding_model = args.embedding_config.model

    if args.index_dir:
        return
    base_index_dir = default_index_dir(
        vector_store_type=args.vector_store,
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
    )
    args.index_dir = apply_chunk_index_suffix(base_index_dir, args.chunks)


def apply_chunk_index_suffix(index_dir: str, chunks: str) -> str:
    chunk_path = Path(chunks)
    if chunk_path.name == "chunks_v2.jsonl":
        return index_dir

    suffix_parts = []
    if "shared_file" in chunk_path.parts and chunk_path.parent.name:
        suffix_parts.append(chunk_path.parent.name)
    suffix_parts.append(chunk_path.stem)
    suffix = re.sub(r"[^a-zA-Z0-9]+", "_", "_".join(suffix_parts)).strip("_").lower()
    if not suffix:
        return index_dir

    path = Path(index_dir)
    if path.name.endswith(f"_{suffix}"):
        return str(path)
    return str(path.with_name(f"{path.name}_{suffix}"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a vector index for dense retrieval.")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--vector-store", choices=["faiss", "chroma"], default="faiss")
    parser.add_argument("--index-dir", help="Defaults depend on vector store and embedding preset.")
    parser.add_argument("--embedding-preset", choices=embedding_preset_choices(), default="openai-small")
    parser.add_argument("--embedding-provider", choices=["openai", "huggingface"])
    parser.add_argument("--embedding-model", help="Override the model id from --embedding-preset.")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    args = parser.parse_args()

    load_dotenv()
    resolve_index_dir(args)

    RAGPipeline(
        chunk_path=args.chunks,
        api_key=os.getenv("OPENAI_API_KEY"),
        retriever_type="dense",
        vector_store_type=args.vector_store,
        index_dir=args.index_dir,
        embedding_preset=args.embedding_preset,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        build_dense_index=True,
        embedding_batch_size=args.batch_size,
        chroma_collection=args.chroma_collection,
    )

    print(f"vector_store: {args.vector_store}")
    print(f"chunks: {args.chunks}")
    print(f"index_dir: {args.index_dir}")
    print(f"embedding_preset: {args.embedding_preset}")
    print(f"embedding_provider: {args.embedding_provider}")
    print(f"embedding_model: {args.embedding_model}")
    if args.vector_store == "chroma":
        print(f"chroma_collection: {args.chroma_collection}")


if __name__ == "__main__":
    main()
