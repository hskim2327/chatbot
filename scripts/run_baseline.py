import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from src.embeddings import default_index_dir, embedding_preset_choices, resolve_embedding_config
from src.pipeline import RAGPipeline


DEFAULT_QUERY = "한국가스공사의 차세대 통합정보시스템 구축 사업 예산 규모는 얼마입니까?"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RFP RAG baseline and print retrieved sources + answer.")
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY)
    parser.add_argument("--retriever", choices=["bm25", "dense", "hybrid"], default="dense")
    parser.add_argument("--chunks", default="data/processed/chunks_v2.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--index-dir", help="Defaults depend on vector store and embedding preset.")
    parser.add_argument("--vector-store", choices=["faiss", "chroma"], default="faiss")
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    parser.add_argument("--embedding-preset", choices=embedding_preset_choices(), default="openai-small")
    parser.add_argument("--embedding-provider", choices=["openai", "huggingface"])
    parser.add_argument("--embedding-model", help="Override the model id from --embedding-preset.")
    parser.add_argument("--generator-model", default="gpt-5-mini")
    parser.add_argument("--hybrid-fetch-k", type=int, default=50)
    parser.add_argument("--hybrid-bm25-weight", type=float, default=0.5)
    parser.add_argument("--hybrid-dense-weight", type=float, default=0.5)
    parser.add_argument("--issuer", help="Filter results by issuer/agency name.")
    parser.add_argument("--project", help="Filter results by project name.")
    parser.add_argument("--source-file", help="Filter results by source file name.")
    parser.add_argument("--doc-id", help="Filter results by document id.")
    parser.add_argument("--chunk-id", help="Filter results by chunk id.")
    parser.add_argument(
        "--build-index",
        "--rebuild-index",
        action="store_true",
        dest="build_index",
        help="Build or rebuild the vector index before running dense/hybrid retrieval.",
    )
    parser.add_argument(
        "--no-build-index",
        action="store_true",
        help="Do not auto-build a missing dense index.",
    )
    parser.add_argument("--multi-query", action="store_true", help="Generate multiple query variants and fuse retrieval results.")
    parser.add_argument("--multi-query-count", type=int, default=3)
    parser.add_argument("--multi-query-fetch-k", type=int, default=20)
    parser.add_argument("--rerank", action="store_true", help="Rerank retrieved candidates with a local keyword reranker.")
    parser.add_argument("--rerank-candidates", type=int, default=30)
    parser.add_argument("--compress-context", action="store_true", help="Compress retrieved chunk text before generation.")
    parser.add_argument("--compression-max-chars", type=int, default=1200)
    parser.add_argument("--no-answer", action="store_true", help="Only print retrieved chunks without calling the LLM.")
    parser.add_argument("--preview-chars", type=int, default=500)
    parser.add_argument("--save", action="store_true", help="Save the run result as JSON.")
    parser.add_argument("--output", help="Exact JSON output path. Implies --save.")
    parser.add_argument("--output-dir", default="outputs/runs")
    args = parser.parse_args()

    load_dotenv()
    resolve_index_dir(args)

    metadata_filter = build_metadata_filter(args)
    should_build_index = should_build_dense_index(args)

    print_run_config(args, metadata_filter, should_build_index)

    pipeline = RAGPipeline(
        chunk_path=args.chunks,
        api_key=os.getenv("OPENAI_API_KEY"),
        retriever_type=args.retriever,
        top_k=args.top_k,
        index_dir=args.index_dir,
        embedding_preset=args.embedding_preset,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        generator_model=args.generator_model,
        build_dense_index=should_build_index,
        metadata_filter=metadata_filter,
        hybrid_fetch_k=args.hybrid_fetch_k,
        hybrid_bm25_weight=args.hybrid_bm25_weight,
        hybrid_dense_weight=args.hybrid_dense_weight,
        vector_store_type=args.vector_store,
        chroma_collection=args.chroma_collection,
        multi_query=args.multi_query,
        multi_query_count=args.multi_query_count,
        multi_query_fetch_k=args.multi_query_fetch_k,
        rerank=args.rerank,
        rerank_candidates=args.rerank_candidates,
        compress_context=args.compress_context,
        compression_max_chars=args.compression_max_chars,
    )

    result = pipeline.run(args.query, generate=not args.no_answer)
    print_result(result, preview_chars=args.preview_chars)

    if args.save or args.output:
        output_path = save_result(args, result, metadata_filter)
        print(f"\n[SAVED]")
        print(output_path)


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


def build_metadata_filter(args: argparse.Namespace) -> dict[str, str]:
    metadata_filter = {
        "issuer": args.issuer,
        "project_name": args.project,
        "source_file": args.source_file,
        "doc_id": args.doc_id,
        "chunk_id": args.chunk_id,
    }
    return {key: value for key, value in metadata_filter.items() if value}


def should_build_dense_index(args: argparse.Namespace) -> bool:
    if args.retriever == "bm25":
        return False

    if args.vector_store == "chroma":
        store_exists = os.path.exists(os.path.join(args.index_dir, "chroma.sqlite3"))
        should_build = args.build_index or (not store_exists and not args.no_build_index)
    else:
        index_path = os.path.join(args.index_dir, "index.faiss")
        store_exists = os.path.exists(index_path)
        should_build = args.build_index or (not store_exists and not args.no_build_index)

    if should_build:
        if args.build_index and store_exists:
            print(f"[INFO] rebuilding {args.vector_store} index at {args.index_dir}")
        else:
            print(f"[INFO] {args.vector_store} index not found. building index at {args.index_dir}")
    elif not store_exists:
        print(f"[ERROR] {args.vector_store} index not found.")
        print("Run without --no-build-index to build it automatically, or pass --build-index.")
        raise SystemExit(1)

    return should_build


def print_run_config(args: argparse.Namespace, metadata_filter: dict[str, str], should_build_index: bool) -> None:
    print("[RUN CONFIG]")
    print(f"retriever: {args.retriever}")
    print(f"top_k: {args.top_k}")
    print(f"chunks: {args.chunks}")
    print(f"index_dir: {args.index_dir}")
    print(f"vector_store: {args.vector_store}")
    print(f"chroma_collection: {args.chroma_collection}")
    print(f"embedding_preset: {args.embedding_preset}")
    print(f"embedding_provider: {args.embedding_provider}")
    print(f"embedding_model: {args.embedding_model}")
    print(f"generator_model: {args.generator_model}")
    print(f"build_index: {should_build_index}")
    print(f"multi_query: {args.multi_query} count={args.multi_query_count}")
    print(f"rerank: {args.rerank} candidates={args.rerank_candidates}")
    print(f"compress_context: {args.compress_context} max_chars={args.compression_max_chars}")
    if args.retriever == "hybrid":
        print(f"hybrid_fetch_k: {args.hybrid_fetch_k}")
        print(f"hybrid_weights: bm25={args.hybrid_bm25_weight}, dense={args.hybrid_dense_weight}")
    print(f"metadata_filter: {metadata_filter or 'None'}")
    print(f"answer_generation: {not args.no_answer}")


def print_result(result: dict[str, Any], preview_chars: int) -> None:
    print("\n[QUESTION]")
    print(result["query"])

    print("\n[RETRIEVER]")
    print(result["retriever_type"])

    print("\n[EMBEDDING]")
    print(f"preset: {result.get('embedding_preset')}")
    print(f"provider: {result.get('embedding_provider')}")
    print(f"model: {result.get('embedding_model')}")

    print("\n[RETRIEVED SOURCES]")
    for rank, item in enumerate(result["retrieved"], 1):
        metadata = item.get("metadata", {})
        text = item.get("text", "").replace("\n", " ")
        score = item.get("score")
        score_text = f"{score:.4f}" if score is not None else "None"

        print(f"\n--- source {rank} ---")
        print(f"score: {score_text}")
        print(f"bm25_score: {format_optional_score(item.get('bm25_score'))}")
        print(f"dense_score: {format_optional_score(item.get('dense_score'))}")
        print(f"bm25_rank: {item.get('bm25_rank')}")
        print(f"dense_rank: {item.get('dense_rank')}")
        print(f"rerank_score: {format_optional_score(item.get('rerank_score'))}")
        print(f"rerank_rank: {item.get('rerank_rank')}")
        print(f"compression_ratio: {format_optional_score(item.get('compression_ratio'))}")
        if item.get("matched_queries"):
            print(f"matched_queries: {item.get('matched_queries')}")
        print(f"chunk_id: {item.get('chunk_id')}")
        print(f"doc_id: {item.get('doc_id')}")
        print(f"source_file: {metadata.get('source_file')}")
        print(f"project: {metadata.get('project_name')}")
        print(f"issuer: {metadata.get('issuer')}")
        print(f"budget: {format_budget(metadata.get('budget'))}")
        print(f"amounts: {metadata.get('amounts')}")
        print(f"section_path: {metadata.get('section_path')}")
        print(f"preview: {text[:preview_chars]}")

    if result.get("answer") is not None:
        print("\n[ANSWER]")
        print(result["answer"])


def save_result(args: argparse.Namespace, result: dict[str, Any], metadata_filter: dict[str, str]) -> Path:
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = Path(args.output_dir) / f"{timestamp}_{args.retriever}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "retriever": args.retriever,
            "chunks": args.chunks,
            "top_k": args.top_k,
            "index_dir": args.index_dir,
            "vector_store": args.vector_store,
            "chroma_collection": args.chroma_collection,
            "embedding_preset": args.embedding_preset,
            "embedding_provider": args.embedding_provider,
            "embedding_model": args.embedding_model,
            "generator_model": args.generator_model,
            "hybrid_fetch_k": args.hybrid_fetch_k,
            "hybrid_bm25_weight": args.hybrid_bm25_weight,
            "hybrid_dense_weight": args.hybrid_dense_weight,
            "metadata_filter": metadata_filter,
            "multi_query": args.multi_query,
            "multi_query_count": args.multi_query_count,
            "multi_query_fetch_k": args.multi_query_fetch_k,
            "rerank": args.rerank,
            "rerank_candidates": args.rerank_candidates,
            "compress_context": args.compress_context,
            "compression_max_chars": args.compression_max_chars,
            "answer_generation": not args.no_answer,
        },
        "result": result,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def format_budget(value: Any) -> str:
    if value in (None, ""):
        return "정보 없음"
    try:
        return f"{int(float(value)):,}원"
    except (TypeError, ValueError):
        return str(value)


def format_optional_score(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    main()
