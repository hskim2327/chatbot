import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if __package__ is None and __spec__ is None:
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

EVAL_SRC = Path(__file__).resolve().parents[1] / "eval" / "evaluation" / "src"
if str(EVAL_SRC) not in sys.path:
    sys.path.insert(0, str(EVAL_SRC))

from rag_eval.loaders import load_eval_csvs, load_predictions_jsonl, merge_eval_predictions

from src.generation import (
    build_generation_input,
    dedupe_repeated_lines,
    enrich_retrieved_contexts,
    load_chunks_by_doc,
    validate_generation_answer,
)
from src.generator import HuggingFaceGenerator


DEFAULT_PREDICTIONS = (
    "outputs/predictions/"
    "74_dense_conditional_qdecomp_v2_rrf_multi_relaxed_filter_kept_per50_diverse250_"
    "soyeon_125_kure_chroma_hnsw_tuned_canonical.jsonl"
)
DEFAULT_CHUNK_SIDECAR = "indexes/chroma_kure_v1_soyeon_125_260520_chunks_v2_125/chunks.json"
DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate answer samples from final retrieval predictions with a local HF model."
    )
    parser.add_argument("--predictions", default=DEFAULT_PREDICTIONS)
    parser.add_argument("--eval-dir", default="data/eval")
    parser.add_argument("--canonical-only", action="store_true", default=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--types", nargs="*", help="Optional eval types, e.g. A B C")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", help="cuda or cpu. Defaults to cuda if available.")
    parser.add_argument("--torch-dtype", default="auto", help="auto, float16, bfloat16, or float32")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--context-max-chars", type=int, default=1200)
    parser.add_argument("--snippets-per-context", type=int, default=3)
    parser.add_argument("--chunk-sidecar", default=DEFAULT_CHUNK_SIDECAR)
    parser.add_argument("--max-extra-contexts", type=int, default=5)
    parser.add_argument("--max-extra-per-doc", type=int, default=2)
    parser.add_argument("--no-context-enrichment", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts and review file without loading the generation model.")
    parser.add_argument("--output", help="Defaults to outputs/generation/<timestamp>_answer_samples.jsonl")
    parser.add_argument("--review-output", help="Defaults to outputs/generation/<timestamp>_answer_review.md")
    args = parser.parse_args()

    load_dotenv()
    output_path, review_path = resolve_outputs(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)

    rows = select_rows(args)
    if not rows:
        raise SystemExit("No rows selected for generation.")

    chunks_by_doc = {}
    if not args.no_context_enrichment and args.chunk_sidecar:
        chunks_by_doc = load_chunks_by_doc(args.chunk_sidecar)
        if chunks_by_doc:
            print(f"[INFO] loaded generation context sidecar: {args.chunk_sidecar}")
        else:
            print(f"[WARN] generation context sidecar not found or empty: {args.chunk_sidecar}")

    generator = None
    if not args.dry_run:
        generator = HuggingFaceGenerator(
            model_name=args.model,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            device=args.device,
            torch_dtype=args.torch_dtype,
        )

    review_sections = [render_review_header(args, rows)]
    with output_path.open("w", encoding="utf-8") as out_file:
        for index, row in enumerate(rows, 1):
            started = time.perf_counter()
            retrieved_contexts = row.get("retrieved_contexts") or []
            retrieved_contexts = enrich_retrieved_contexts(
                question=row["question"],
                retrieved_contexts=retrieved_contexts,
                chunks_by_doc=chunks_by_doc,
                max_extra_contexts=args.max_extra_contexts,
                max_extra_per_doc=args.max_extra_per_doc,
            )
            generation_input = build_generation_input(
                question=row["question"],
                retrieved_contexts=retrieved_contexts,
                context_max_chars=args.context_max_chars,
                snippets_per_context=args.snippets_per_context,
            )

            if args.dry_run:
                answer = ""
                latency_ms = 0
                guardrails = {"confidence": "not_run", "warnings": ["dry_run"]}
            else:
                answer = generator.generate_prompt(generation_input.prompt)
                answer = dedupe_repeated_lines(answer)
                latency_ms = int((time.perf_counter() - started) * 1000)
                guardrails = validate_generation_answer(answer, generation_input)

            payload = build_payload(row, generation_input, answer, guardrails, latency_ms, args)
            out_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            review_sections.append(render_review_case(payload))
            print(
                f"[PROGRESS] {index}/{len(rows)} {row['id']} "
                f"type={row.get('type')} qtype={generation_input.question_type}"
            )

    review_path.write_text("\n\n".join(review_sections), encoding="utf-8")
    print(f"[DONE] jsonl: {output_path}")
    print(f"[DONE] review: {review_path}")
    if args.dry_run:
        print("[DRY RUN] prompts were generated without loading a Hugging Face model.")


def select_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    eval_df = load_eval_csvs(Path(args.eval_dir), canonical_only=args.canonical_only)
    pred_df = load_predictions_jsonl(Path(args.predictions))
    merged = merge_eval_predictions(eval_df, pred_df)
    merged = merged[~merged["prediction_missing"]].copy()

    if args.ids:
        merged = merged[merged["id"].isin(args.ids)]
    if args.types:
        wanted = {item.upper() for item in args.types}
        merged = merged[merged["type"].astype(str).str.upper().isin(wanted)]
    if args.limit and args.limit > 0:
        merged = merged.head(args.limit)

    rows = []
    for _, row in merged.iterrows():
        retrieved_contexts = row.get("retrieved_contexts")
        rows.append(
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "difficulty": row.get("difficulty"),
                "question": _first_non_empty(row, "question_eval", "question", "question_pred"),
                "ground_truth_answer": row.get("ground_truth_answer"),
                "ground_truth_docs": row.get("ground_truth_doc_list"),
                "metadata_filter": row.get("metadata_filter_obj"),
                "retrieved_contexts": retrieved_contexts if isinstance(retrieved_contexts, list) else [],
            }
        )
    return rows


def _first_non_empty(row: Any, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def build_payload(
    row: dict[str, Any],
    generation_input: Any,
    answer: str,
    guardrails: dict[str, Any],
    latency_ms: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "type": row.get("type"),
        "difficulty": row.get("difficulty"),
        "question": row.get("question"),
        "question_type": generation_input.question_type,
        "answer": answer,
        "ground_truth_answer": row.get("ground_truth_answer"),
        "ground_truth_docs": row.get("ground_truth_docs"),
        "retrieved_docs": [record.get("filename") for record in generation_input.context_records],
        "field_candidates": generation_input.field_candidates,
        "evidence_sentences": generation_input.evidence_sentences,
        "guardrails": guardrails,
        "latency_ms": latency_ms,
        "generation_model": args.model,
        "generation_config": {
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_new_tokens": args.max_new_tokens,
            "context_max_chars": args.context_max_chars,
            "snippets_per_context": args.snippets_per_context,
            "chunk_sidecar": args.chunk_sidecar,
            "context_enrichment": not args.no_context_enrichment,
            "max_extra_contexts": args.max_extra_contexts,
            "max_extra_per_doc": args.max_extra_per_doc,
            "dry_run": args.dry_run,
        },
        "prompt": generation_input.prompt,
    }


def render_review_header(args: argparse.Namespace, rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "# Generation Sample Review",
            "",
            f"- created_at: {datetime.now(timezone.utc).isoformat()}",
            f"- model: {args.model}",
            f"- predictions: {args.predictions}",
            f"- selected_questions: {len(rows)}",
            f"- dry_run: {args.dry_run}",
            f"- context_enrichment: {not args.no_context_enrichment}",
            f"- chunk_sidecar: {args.chunk_sidecar}",
            "",
            "평가자는 각 케이스에 대해 검색 문제인지, generation 문제인지, 데이터 문제인지 분리해서 기록한다.",
        ]
    )


def render_review_case(payload: dict[str, Any]) -> str:
    guardrails = payload.get("guardrails") or {}
    retrieved_docs = payload.get("retrieved_docs") or []
    docs_text = "\n".join(f"  - {doc}" for doc in retrieved_docs if doc)
    evidence = payload.get("evidence_sentences") or []
    evidence_text = "\n".join(
        f"  - rank {item.get('rank')} | {item.get('filename')}: {item.get('sentence')}"
        for item in evidence[:5]
    )
    return f"""## {payload.get('id')} | type {payload.get('type')} | {payload.get('question_type')}

### Question
{payload.get('question')}

### Generated Answer
{payload.get('answer') or '(dry-run: answer not generated)'}

### Ground Truth Answer
{payload.get('ground_truth_answer')}

### Retrieved Docs
{docs_text or '- 없음'}

### Evidence Candidates
{evidence_text or '- 없음'}

### Guardrails
- confidence: {guardrails.get('confidence')}
- warnings: {guardrails.get('warnings')}

### Human Evaluation
- correctness:
- evidence_grounded:
- failure_type:
- memo:
""".strip()


def resolve_outputs(args: argparse.Namespace) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = Path(args.output) if args.output else Path("outputs/generation") / f"{timestamp}_answer_samples.jsonl"
    review = Path(args.review_output) if args.review_output else Path("outputs/generation") / f"{timestamp}_answer_review.md"
    return output, review


if __name__ == "__main__":
    main()
