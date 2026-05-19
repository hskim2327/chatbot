import argparse
import os
import sys

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.embeddings import create_embedder, default_index_dir, embedding_preset_choices, resolve_embedding_config
from src.retriever import DenseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a FAISS index from processed RFP chunks.")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--index-dir", help="Defaults depend on embedding preset.")
    parser.add_argument("--embedding-preset", choices=embedding_preset_choices(), default="openai-small")
    parser.add_argument("--embedding-provider", choices=["openai", "huggingface"])
    parser.add_argument("--embedding-model", help="Override the model id from --embedding-preset.")
    parser.add_argument("--model", help="Deprecated alias for --embedding-model.")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    load_dotenv()
    if args.model and not args.embedding_model:
        args.embedding_model = args.model

    embedding_config = resolve_embedding_config(
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
    )
    args.embedding_provider = embedding_config.provider
    args.embedding_model = embedding_config.model
    if not args.index_dir:
        args.index_dir = default_index_dir(
            vector_store_type="faiss",
            preset=args.embedding_preset,
            provider=args.embedding_provider,
            model=args.embedding_model,
        )

    chunks = load_chunks_jsonl(args.chunks)
    embedder = create_embedder(
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
        api_key=os.getenv("OPENAI_API_KEY"),
        batch_size=args.batch_size,
    )
    retriever = DenseRetriever(chunks=chunks, embedder=embedder)
    retriever.build_index(batch_size=args.batch_size)
    retriever.save(args.index_dir)

    print(f"indexed chunks: {len(chunks)}")
    print(f"index dir: {args.index_dir}")
    print(f"embedding preset: {args.embedding_preset}")
    print(f"embedding provider: {args.embedding_provider}")
    print(f"embedding model: {args.embedding_model}")


if __name__ == "__main__":
    main()
