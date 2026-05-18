import argparse
import os
import sys

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.pipeline import RAGPipeline


DEFAULT_QUERY = "한국가스공사의 차세대 통합정보시스템 구축 사업 예산 규모는 얼마입니까?"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RFP RAG baseline and print retrieved sources + answer.")
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--retriever", choices=["bm25", "dense"], default="dense")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--index-dir", default="indexes/faiss_openai")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--generator-model", default="gpt-5-mini")
    parser.add_argument(
        "--build-index",
        "--rebuild-index",
        action="store_true",
        dest="build_index",
        help="Build or rebuild the FAISS index before running dense retrieval.",
    )
    parser.add_argument(
        "--no-build-index",
        action="store_true",
        help="Do not auto-build a missing dense index.",
    )
    parser.add_argument("--no-answer", action="store_true", help="Only print retrieved chunks without calling the LLM.")
    parser.add_argument("--preview-chars", type=int, default=500)
    args = parser.parse_args()

    load_dotenv()

    index_path = os.path.join(args.index_dir, "index.faiss")
    index_exists = os.path.exists(index_path)
    should_build_index = args.retriever == "dense" and (
        args.build_index or (not index_exists and not args.no_build_index)
    )

    if args.retriever == "dense" and should_build_index:
        if args.build_index and index_exists:
            print(f"[INFO] rebuilding dense index at {args.index_dir}")
        else:
            print(f"[INFO] dense index not found. building index at {args.index_dir}")
    elif args.retriever == "dense" and not index_exists:
        print("[ERROR] dense index not found.")
        print("Run this first:")
        print(f".venv/bin/python scripts/build_faiss_index.py --index-dir {args.index_dir}")
        print("Or run without --no-build-index to build it automatically.")
        raise SystemExit(1)

    pipeline = RAGPipeline(
        chunk_path=args.chunks,
        api_key=os.getenv("OPENAI_API_KEY"),
        retriever_type=args.retriever,
        top_k=args.top_k,
        index_dir=args.index_dir,
        embedding_model=args.embedding_model,
        generator_model=args.generator_model,
        build_dense_index=should_build_index,
    )

    result = pipeline.run(args.query, generate=not args.no_answer)
    print_result(result, preview_chars=args.preview_chars)


def print_result(result: dict, preview_chars: int) -> None:
    print("\n[QUESTION]")
    print(result["query"])

    print("\n[RETRIEVER]")
    print(result["retriever_type"])

    print("\n[RETRIEVED SOURCES]")
    for rank, item in enumerate(result["retrieved"], 1):
        metadata = item.get("metadata", {})
        text = item.get("text", "").replace("\n", " ")
        score = item.get("score")
        score_text = f"{score:.4f}" if score is not None else "None"

        print(f"\n--- source {rank} ---")
        print(f"score: {score_text}")
        print(f"chunk_id: {item.get('chunk_id')}")
        print(f"doc_id: {item.get('doc_id')}")
        print(f"project: {metadata.get('project_name')}")
        print(f"issuer: {metadata.get('issuer')}")
        print(f"preview: {text[:preview_chars]}")

    if result.get("answer") is not None:
        print("\n[ANSWER]")
        print(result["answer"])


if __name__ == "__main__":
    main()
