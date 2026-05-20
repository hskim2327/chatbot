import argparse
import ast
import csv
import json
import os
import re
import sys
import time
import unicodedata
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


CANONICAL_BATCH_START = 1
CANONICAL_BATCH_END = 25
REQUIRED_EVAL_COLUMNS = {
    "id",
    "type",
    "difficulty",
    "question",
    "ground_truth_answer",
    "ground_truth_docs",
    "metadata_filter",
    "history",
}
MULTI_AGENCY_MARKERS = {"다중", "multi", "multiple"}
COMMON_ORG_MARKERS = (
    "사단법인",
    "재단법인",
    "주식회사",
    "(사)",
    "(재)",
    "(주)",
    "㈜",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate eval-compatible predictions JSONL from the RAG pipeline.")
    parser.add_argument("--eval-dir", default="data/eval", help="Folder containing eval_batch_*.csv files.")
    parser.add_argument("--output", help="Predictions JSONL path. Defaults to outputs/predictions/<timestamp>_<config>.jsonl.")
    parser.add_argument("--output-dir", default="outputs/predictions")
    parser.add_argument("--canonical-only", action="store_true", help="Use eval_batch_01.csv through eval_batch_25.csv only.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N questions. Useful for smoke tests.")
    parser.add_argument("--ids", nargs="*", help="Optional list of eval question ids to process, e.g. Q001 Q002.")
    parser.add_argument(
        "--no-expand-multi-agency-filter",
        action="store_false",
        dest="expand_multi_agency_filter",
        help="Do not infer concrete agencies when eval metadata_filter has agency='다중'.",
    )

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
    parser.add_argument("--build-index", action="store_true", help="Build or rebuild a vector index before generating predictions.")
    parser.add_argument("--embedding-batch-size", type=int, default=100)

    parser.add_argument("--multi-query", action="store_true")
    parser.add_argument("--multi-query-count", type=int, default=3)
    parser.add_argument("--multi-query-fetch-k", type=int, default=20)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-candidates", type=int, default=30)
    parser.add_argument("--compress-context", action="store_true")
    parser.add_argument("--compression-max-chars", type=int, default=1200)

    parser.add_argument("--generate-answer", action="store_true", help="Generate answers with the OpenAI generator. Default is retrieval-only.")
    parser.add_argument("--context-max-chars", type=int, default=1200, help="Trim each retrieved context text in predictions JSONL. 0 keeps full text.")
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()

    load_dotenv()
    resolve_embedding_args(args)
    ensure_index_ready(args)

    rows = load_eval_rows(Path(args.eval_dir), canonical_only=args.canonical_only)
    rows = filter_eval_rows(rows, ids=args.ids, limit=args.limit)
    if not rows:
        raise SystemExit("No eval rows selected.")

    output_path = resolve_output_path(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print_config(args, len(rows), output_path)

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
        build_dense_index=args.build_index,
        embedding_batch_size=args.embedding_batch_size,
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

    issuer_aliases = build_issuer_aliases(pipeline.chunks)

    with output_path.open("w", encoding="utf-8") as file:
        for idx, row in enumerate(rows, 1):
            prediction = build_prediction(row, pipeline, args, issuer_aliases)
            file.write(json.dumps(prediction, ensure_ascii=False) + "\n")
            if args.progress_every and (idx == 1 or idx % args.progress_every == 0 or idx == len(rows)):
                print(f"[PROGRESS] {idx}/{len(rows)} wrote {prediction['id']}")

    print(f"[DONE] predictions: {output_path}")
    print("[NEXT] Phase 1 evaluation example:")
    canonical_flag = " --canonical-only" if args.canonical_only else ""
    print(f".venv/bin/python eval/scripts/run_evaluation.py --predictions {output_path}{canonical_flag}")


def resolve_embedding_args(args: argparse.Namespace) -> None:
    config = resolve_embedding_config(
        preset=args.embedding_preset,
        provider=args.embedding_provider,
        model=args.embedding_model,
    )
    args.embedding_provider = config.provider
    args.embedding_model = config.model
    if not args.index_dir:
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


def ensure_index_ready(args: argparse.Namespace) -> None:
    if args.retriever == "bm25" or args.build_index:
        return
    if args.vector_store == "faiss":
        index_path = Path(args.index_dir) / "index.faiss"
        if not index_path.exists():
            raise SystemExit(
                f"Dense index not found at {index_path}. "
                "Build it first with scripts/build_vector_index.py or pass --build-index."
            )
    elif args.vector_store == "chroma":
        chroma_path = Path(args.index_dir) / "chroma.sqlite3"
        if not chroma_path.exists():
            raise SystemExit(
                f"Chroma index not found at {chroma_path}. "
                "Build it first with scripts/build_vector_index.py or pass --build-index."
            )


def load_eval_rows(eval_dir: Path, canonical_only: bool) -> list[dict[str, Any]]:
    if canonical_only:
        csv_paths = [eval_dir / f"eval_batch_{idx:02d}.csv" for idx in range(CANONICAL_BATCH_START, CANONICAL_BATCH_END + 1)]
        missing = [str(path) for path in csv_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing canonical eval CSV files: {missing}")
    else:
        csv_paths = sorted(eval_dir.glob("*.csv"))
        if not csv_paths:
            raise FileNotFoundError(f"No eval CSV files found under {eval_dir}")

    rows: list[dict[str, Any]] = []
    for csv_path in csv_paths:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            missing_columns = REQUIRED_EVAL_COLUMNS - set(reader.fieldnames or [])
            if missing_columns:
                raise ValueError(f"{csv_path} is missing required columns: {sorted(missing_columns)}")
            for row in reader:
                row["source_eval_file"] = csv_path.name
                rows.append(row)
    return rows


def filter_eval_rows(rows: list[dict[str, Any]], ids: list[str] | None, limit: int) -> list[dict[str, Any]]:
    if ids:
        wanted = set(ids)
        rows = [row for row in rows if row.get("id") in wanted]
    if limit and limit > 0:
        rows = rows[:limit]
    return rows


def build_prediction(
    row: dict[str, Any],
    pipeline: RAGPipeline,
    args: argparse.Namespace,
    issuer_aliases: list[tuple[str, set[str]]],
) -> dict[str, Any]:
    question = str(row.get("question") or "")
    raw_metadata_filter = parse_structured_cell(row.get("metadata_filter"), default={})
    metadata_filter = resolve_eval_metadata_filter(
        raw_metadata_filter,
        question=question,
        issuer_aliases=issuer_aliases,
        expand_multi_agency_filter=args.expand_multi_agency_filter,
    )

    started = time.perf_counter()
    result = pipeline.run(
        question,
        generate=args.generate_answer,
        metadata_filter=metadata_filter,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "id": row.get("id"),
        "question": question,
        "answer": result.get("answer") or "",
        "retrieved_contexts": [
            format_context(rank, item, context_max_chars=args.context_max_chars)
            for rank, item in enumerate(result.get("retrieved", []), 1)
        ],
        "latency_ms": latency_ms,
        "model_name": args.generator_model if args.generate_answer else "not_generated",
        "embedding_model": result.get("embedding_model") or args.embedding_model,
        "retriever_config": build_retriever_config(args),
        "metadata_filter": metadata_filter,
        "raw_metadata_filter": raw_metadata_filter if isinstance(raw_metadata_filter, dict) else {},
        "source_eval_file": row.get("source_eval_file"),
    }


def build_issuer_aliases(chunks: list[dict[str, Any]]) -> list[tuple[str, set[str]]]:
    issuers = {
        str((chunk.get("metadata") or {}).get("issuer") or "").strip()
        for chunk in chunks
    }
    return [
        (issuer, aliases)
        for issuer in sorted(issuers, key=len, reverse=True)
        if issuer and (aliases := make_issuer_aliases(issuer))
    ]


def make_issuer_aliases(issuer: str) -> set[str]:
    aliases = {normalize_for_match(issuer)}

    without_parentheses = re.sub(r"\([^)]*\)", "", issuer)
    without_parentheses = re.sub(r"（[^）]*）", "", without_parentheses)
    aliases.add(normalize_for_match(without_parentheses))

    cleaned = issuer
    for marker in COMMON_ORG_MARKERS:
        cleaned = cleaned.replace(marker, "")
    aliases.add(normalize_for_match(cleaned))

    cleaned_without_parentheses = without_parentheses
    for marker in COMMON_ORG_MARKERS:
        cleaned_without_parentheses = cleaned_without_parentheses.replace(marker, "")
    aliases.add(normalize_for_match(cleaned_without_parentheses))

    if "koica" in issuer.casefold():
        aliases.update({"koica", "코이카", "코이카전자조달"})

    return {alias for alias in aliases if len(alias) >= 3}


def resolve_eval_metadata_filter(
    raw_metadata_filter: Any,
    question: str,
    issuer_aliases: list[tuple[str, set[str]]],
    expand_multi_agency_filter: bool = True,
) -> dict[str, Any]:
    if not isinstance(raw_metadata_filter, dict):
        return {}

    resolved: dict[str, Any] = {}
    for key, value in raw_metadata_filter.items():
        if is_multi_agency_filter(key, value):
            if expand_multi_agency_filter:
                inferred = infer_issuers_from_question(question, issuer_aliases)
                if inferred:
                    resolved[key] = inferred
            continue
        if value not in (None, "", []):
            resolved[key] = value
    return resolved


def is_multi_agency_filter(key: str, value: Any) -> bool:
    if str(key).casefold() not in {"agency", "issuer"}:
        return False
    return isinstance(value, str) and value.strip().casefold() in MULTI_AGENCY_MARKERS


def infer_issuers_from_question(question: str, issuer_aliases: list[tuple[str, set[str]]]) -> list[str]:
    normalized_question = normalize_for_match(question)
    matched: list[str] = []
    seen: set[str] = set()

    for issuer, aliases in issuer_aliases:
        if issuer in seen:
            continue
        if any(alias and alias in normalized_question for alias in aliases):
            matched.append(issuer)
            seen.add(issuer)

    return matched


def normalize_for_match(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value)).casefold()
    text = text.replace("㈜", "주")
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def format_context(rank: int, item: dict[str, Any], context_max_chars: int) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    text = str(item.get("text") or "")
    if context_max_chars and context_max_chars > 0:
        text = text[:context_max_chars]

    context = {
        "rank": rank,
        "filename": metadata.get("source_file"),
        "doc_id": item.get("doc_id"),
        "chunk_id": item.get("chunk_id"),
        "score": item.get("score"),
        "text": text,
        "metadata": metadata,
    }
    for key in (
        "bm25_score",
        "dense_score",
        "bm25_rank",
        "dense_rank",
        "rerank_score",
        "rerank_rank",
        "compression_ratio",
        "matched_queries",
    ):
        if key in item:
            context[key] = item.get(key)
    return context


def build_retriever_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "retriever_type": args.retriever,
        "top_k": args.top_k,
        "vector_store": args.vector_store,
        "index_dir": args.index_dir,
        "embedding_preset": args.embedding_preset,
        "embedding_provider": args.embedding_provider,
        "embedding_model": args.embedding_model,
        "reranker": bool(args.rerank),
        "multi_query": bool(args.multi_query),
        "compress_context": bool(args.compress_context),
        "expand_multi_agency_filter": bool(args.expand_multi_agency_filter),
        "hybrid_fetch_k": args.hybrid_fetch_k if args.retriever == "hybrid" else "",
        "hybrid_bm25_weight": args.hybrid_bm25_weight if args.retriever == "hybrid" else "",
        "hybrid_dense_weight": args.hybrid_dense_weight if args.retriever == "hybrid" else "",
        "chunk_size": "pre_chunked",
        "chunk_overlap": "pre_chunked",
    }


def parse_structured_cell(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except Exception:
            continue
    return default


def resolve_output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    parts = [args.retriever, args.embedding_preset]
    if args.rerank:
        parts.append("rerank")
    if args.multi_query:
        parts.append("multiquery")
    filename = f"{timestamp}_{'_'.join(parts)}.jsonl"
    return Path(args.output_dir) / filename


def print_config(args: argparse.Namespace, row_count: int, output_path: Path) -> None:
    print("[EVAL PREDICTION CONFIG]")
    print(f"rows: {row_count}")
    print(f"eval_dir: {args.eval_dir}")
    print(f"canonical_only: {args.canonical_only}")
    print(f"output: {output_path}")
    print(f"retriever: {args.retriever}")
    print(f"top_k: {args.top_k}")
    print(f"vector_store: {args.vector_store}")
    print(f"index_dir: {args.index_dir}")
    print(f"embedding_preset: {args.embedding_preset}")
    print(f"embedding_provider: {args.embedding_provider}")
    print(f"embedding_model: {args.embedding_model}")
    print(f"expand_multi_agency_filter: {args.expand_multi_agency_filter}")
    print(f"generate_answer: {args.generate_answer}")


if __name__ == "__main__":
    main()
