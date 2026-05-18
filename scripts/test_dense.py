import argparse
import os
import sys

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.embeddings import OpenAIEmbedder
from src.retriever import DenseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a dense retrieval smoke test against a saved FAISS index.")
    parser.add_argument("query")
    parser.add_argument("--index-dir", default="indexes/faiss_openai")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    load_dotenv()

    embedder = OpenAIEmbedder(model=args.model)
    retriever = DenseRetriever.from_index(args.index_dir, embedder=embedder)
    results = retriever.retrieve(args.query, top_k=args.top_k)

    for rank, item in enumerate(results, 1):
        print(f"[{rank}] score={item['score']:.4f} chunk_id={item['chunk_id']} doc_id={item['doc_id']}")
        print(item["text"][:300].replace("\n", " "))
        print()


if __name__ == "__main__":
    main()
