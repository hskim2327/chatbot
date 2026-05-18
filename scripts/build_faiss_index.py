import argparse
import os
import sys

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.embeddings import OpenAIEmbedder
from src.retriever import DenseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a FAISS index from processed RFP chunks.")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--index-dir", default="indexes/faiss_openai")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    load_dotenv()

    chunks = load_chunks_jsonl(args.chunks)
    embedder = OpenAIEmbedder(model=args.model)
    retriever = DenseRetriever(chunks=chunks, embedder=embedder)
    retriever.build_index(batch_size=args.batch_size)
    retriever.save(args.index_dir)

    print(f"indexed chunks: {len(chunks)}")
    print(f"index dir: {args.index_dir}")
    print(f"embedding model: {args.model}")


if __name__ == "__main__":
    main()
