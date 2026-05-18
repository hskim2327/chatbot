import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.embeddings import OpenAIEmbedder
from src.evaluation.retrieval_eval import evaluate_retriever, load_eval_jsonl, parse_top_k, print_report
from src.retriever import DenseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate dense retrieval with OpenAI embeddings and FAISS.")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--eval", default="data/eval/retrieval_questions.jsonl")
    parser.add_argument("--index-dir", default="indexes/faiss_openai")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--top-k", default="1,3,5,10")
    parser.add_argument("--output", default="outputs/dense_openai.json")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    embedder = OpenAIEmbedder(model=args.model)
    index_dir = Path(args.index_dir)

    if args.rebuild or not (index_dir / "index.faiss").exists():
        chunks = load_chunks_jsonl(args.chunks)
        retriever = DenseRetriever(chunks=chunks, embedder=embedder)
        retriever.build_index(batch_size=args.batch_size)
        retriever.save(index_dir)
        print(f"built index: {index_dir} ({len(chunks)} chunks)")
    else:
        retriever = DenseRetriever.from_index(index_dir, embedder=embedder)
        print(f"loaded index: {index_dir} ({len(retriever.chunks)} chunks)")

    examples = load_eval_jsonl(args.eval)
    metrics = evaluate_retriever(retriever, examples, parse_top_k(args.top_k))
    print_report(metrics, title="OpenAI Dense Retrieval")
    _write_json(args.output, metrics)


def _write_json(path: str, data: dict) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {output_path}")


if __name__ == "__main__":
    main()
