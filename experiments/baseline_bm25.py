import argparse
import json
import os
import sys
from pathlib import Path

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.data import load_chunks_jsonl
from src.evaluation.retrieval_eval import evaluate_retriever, load_eval_jsonl, parse_top_k, print_report
from src.retriever import BM25Retriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the BM25 retrieval baseline.")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--eval", default="data/eval/retrieval_questions.jsonl")
    parser.add_argument("--top-k", default="1,3,5,10")
    parser.add_argument("--output", default="outputs/baseline_bm25.json")
    args = parser.parse_args()

    chunks = load_chunks_jsonl(args.chunks)
    examples = load_eval_jsonl(args.eval)
    retriever = BM25Retriever(chunks)

    metrics = evaluate_retriever(retriever, examples, parse_top_k(args.top_k))
    print_report(metrics, title="BM25 Retrieval Baseline")
    _write_json(args.output, metrics)


def _write_json(path: str, data: dict) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {output_path}")


if __name__ == "__main__":
    main()
