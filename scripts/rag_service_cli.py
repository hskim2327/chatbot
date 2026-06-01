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

from src.generation import (
    advanced_guardrails,
    build_rfp_generation_input,
    dedupe_repeated_lines,
    load_rfp_generation_resources,
    postprocess_rfp_generation_answer,
)
from src.generator import HuggingFaceGenerator
from src.pipeline import RAGPipeline


DEFAULT_CHUNKS = "data/processed/chunks_v2_690.jsonl"
DEFAULT_INDEX = "indexes/chroma_kure_v1_chunks_v2_690"
DEFAULT_SOURCE_STORE = "data/processed/source_store_v2_690.jsonl"
DEFAULT_MODEL = "unsloth/Qwen3-8B-bnb-4bit"
DEFAULT_BEST_ADAPTER = "outputs/peft/qwen3_8b_qlora_sft_v2_truncfix/adapter"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Small local RAG service CLI: retrieve -> build context -> optional generation -> evidence/warnings."
    )
    parser.add_argument("question", help="User question")
    parser.add_argument("--chunks", default=DEFAULT_CHUNKS)
    parser.add_argument("--index-dir", default=DEFAULT_INDEX)
    parser.add_argument("--source-store-path", default=DEFAULT_SOURCE_STORE)
    parser.add_argument("--context-mode", default="rfp_auto_route_104_114")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retrieval-candidates", type=int, default=75)
    parser.add_argument("--doc-score-candidates", type=int, default=300)
    parser.add_argument("--target-candidates", type=int, default=30)
    parser.add_argument("--embedding-preset", default="kure")
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    parser.add_argument("--no-source-store", action="store_true")
    parser.add_argument("--generate", action="store_true", help="Actually run local HF generation. Omit to inspect context only.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device")
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--adapter-path", help="Optional PEFT/LoRA adapter path for generation.")
    parser.add_argument(
        "--use-best-adapter",
        action="store_true",
        help=f"Use the current best PEFT adapter: {DEFAULT_BEST_ADAPTER}",
    )
    parser.add_argument("--torch-dtype", default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--output", help="Optional JSON output path. Defaults to outputs/service_runs/<timestamp>.json")
    args = parser.parse_args()

    load_dotenv()
    started = time.perf_counter()
    pipeline = RAGPipeline(
        chunk_path=args.chunks,
        retriever_type="dense",
        top_k=args.top_k,
        index_dir=args.index_dir,
        embedding_preset=args.embedding_preset,
        vector_store_type="chroma",
        chroma_collection=args.chroma_collection,
        build_dense_index=False,
        query_decomposition=True,
        decomposition_conditional=True,
        decomposition_candidates_per_query=args.retrieval_candidates,
        decomposition_max_queries=8,
        decomposition_selection="round_robin",
        document_scoring=True,
        doc_score_candidates=args.doc_score_candidates,
        doc_score_method="mean_top_n",
        doc_score_top_n=3,
        target_aware=True,
        target_candidates=args.target_candidates,
        target_quota=1,
        target_min_count=2,
        target_max_count=5,
    )
    retrieved = pipeline.retrieve(args.question)
    retrieval_ms = int((time.perf_counter() - started) * 1000)

    row = {"id": "service_query", "question": args.question, "retrieved_contexts": retrieved}
    resources = load_rfp_generation_resources(
        [row],
        chunks_path=args.index_dir + "/chunks.json" if Path(args.index_dir, "chunks.json").exists() else args.chunks,
        source_store_path=args.source_store_path,
        use_source_store=not args.no_source_store,
    )
    generation_input = build_rfp_generation_input(
        question=args.question,
        retrieved_contexts=retrieved,
        resources=resources,
        context_mode=args.context_mode,
        use_source_store=not args.no_source_store,
    )

    answer = ""
    raw_answer = ""
    guardrails: dict[str, Any] = {"confidence": "not_run", "warnings": ["generation_not_run"]}
    generation_ms = 0
    adapter_path = DEFAULT_BEST_ADAPTER if args.use_best_adapter else args.adapter_path
    load_in_4bit = args.load_in_4bit or args.use_best_adapter

    if args.generate:
        gen_started = time.perf_counter()
        generator = HuggingFaceGenerator(
            model_name=args.model,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            device=args.device,
            torch_dtype=args.torch_dtype,
            load_in_4bit=load_in_4bit,
            enable_thinking=False,
            adapter_path=adapter_path,
        )
        raw_answer = generator.generate_prompt(
            generation_input.prompt,
            system_prompt=generation_input.system_prompt,
        )
        processed = postprocess_rfp_generation_answer(raw_answer, generation_input)
        answer = dedupe_repeated_lines(str(processed.get("answer") or ""))
        generation_input.extra_payload["raw_answer"] = raw_answer
        generation_input.extra_payload["advanced_answer"] = processed
        guardrails = advanced_guardrails(processed)
        generation_ms = int((time.perf_counter() - gen_started) * 1000)

    payload = {
        "question": args.question,
        "answer": answer,
        "raw_answer": raw_answer,
        "retrieval_ms": retrieval_ms,
        "generation_ms": generation_ms,
        "context_mode": args.context_mode,
        "generation_model": args.model,
        "adapter_path": adapter_path,
        "load_in_4bit": load_in_4bit,
        "question_analysis": generation_input.extra_payload.get("question_analysis"),
        "context_char_count": generation_input.extra_payload.get("context_char_count"),
        "guardrails": guardrails,
        "retrieved_top5": [summarize_retrieved(item, rank) for rank, item in enumerate(retrieved[:5], 1)],
        "used_evidence_ids": generation_input.extra_payload.get("used_evidence_ids", []),
        "used_evidence_refs": generation_input.extra_payload.get("used_evidence_refs", []),
        "used_source_store_ids": generation_input.extra_payload.get("used_source_store_ids", []),
        "context_text": generation_input.context_text,
    }

    output = Path(args.output) if args.output else default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print_summary(payload, output)


def summarize_retrieved(item: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "rank": rank,
        "score": item.get("score"),
        "chunk_id": item.get("chunk_id") or metadata.get("chunk_id"),
        "doc_id": item.get("doc_id") or metadata.get("doc_id"),
        "source_file": item.get("source_file") or metadata.get("source_file"),
        "section_path": metadata.get("section_path") or item.get("section_path"),
        "preview": " ".join(str(item.get("text") or item.get("content") or "").split())[:260],
    }


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("outputs/service_runs") / f"rag_service_{stamp}.json"


def print_summary(payload: dict[str, Any], output: Path) -> None:
    analysis = payload.get("question_analysis") or {}
    print("[QUESTION]")
    print(payload.get("question", ""))
    print("\n[ROUTING]")
    print(f"heuristic_task_family: {analysis.get('heuristic_task_family')}")
    print(f"context_profile: {analysis.get('routed_context_profile')}")
    print(f"question_types: {analysis.get('question_types')}")
    print(f"answer_type: {analysis.get('answer_type')}")
    print(f"generation_model: {payload.get('generation_model')}")
    print(f"adapter_path: {payload.get('adapter_path')}")
    print("\n[RETRIEVED TOP5]")
    for item in payload.get("retrieved_top5", []):
        print(f"{item['rank']}. {item.get('source_file')} | chunk={item.get('chunk_id')} | score={item.get('score')}")
    print("\n[CONTEXT]")
    print(f"chars: {payload.get('context_char_count')}")
    print(f"used_evidence_ids: {payload.get('used_evidence_ids')}")
    print(f"used_evidence_refs_count: {len(payload.get('used_evidence_refs') or [])}")
    print(f"used_source_store_ids: {payload.get('used_source_store_ids')}")
    print("\n[ANSWER]")
    print(payload.get("answer") or "(generation not run)")
    print("\n[GUARDRAILS]")
    print(payload.get("guardrails"))
    print("\n[SAVED]")
    print(output)


if __name__ == "__main__":
    main()
