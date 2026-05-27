#!/usr/bin/env python3
"""Experimental retrieval target filtering and redundancy control.

This script is intentionally isolated from the production retrieval modules.
It reuses the existing RAGPipeline and eval metric code, then writes all new
outputs under outputs/retrieval_experiments/<run_name>/.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVAL_SRC = ROOT / "eval/evaluation/src"
if str(EVAL_SRC) not in sys.path:
    sys.path.insert(0, str(EVAL_SRC))

from rag_eval.loaders import load_eval_csvs, load_predictions_jsonl, merge_eval_predictions
from rag_eval.normalization import extract_top_unique_documents, parse_structured_cell
from rag_eval.retrieval_metrics import compute_doc_recall_metrics, compute_retrieval_metrics, first_relevant_rank
from scripts.generate_eval_predictions import (
    build_issuer_aliases,
    format_context,
    resolve_eval_metadata_filter,
)
from src.data import load_chunks_jsonl
from src.generation.context_builder import classify_question
from src.pipeline import RAGPipeline
from src.retriever.target_aware import TargetQueryExtractor

DEFAULT_BASELINE = (
    "outputs/predictions/96_dense_qdecomp_rrf_per75_docscore_mean3_targetaware30_max5_"
    "preserve3_relaxed_filter_kure_chroma_690_canonical.jsonl"
)
DEFAULT_CHUNKS = "indexes/chroma_kure_v1_chunks_v2_690/chunks.json"
DEFAULT_INDEX_DIR = "indexes/chroma_kure_v1_chunks_v2_690"

QUESTION_TYPE_KEYWORDS = {
    "budget": ("예산", "사업비", "기초금액", "금액", "가격", "추정가격", "원", "budget", "amount", "price", "cost"),
    "date_or_period": ("기간", "일정", "마감", "계약기간", "제출마감", "기한", "date", "period", "deadline"),
    "qualification": ("자격", "참가자격", "제한요건", "실적", "요건", "qualification", "requirement"),
    "submission_documents": ("제출서류", "제안서", "구비서류", "첨부", "서류", "submission", "document", "proposal"),
    "general": (),
}
NOTICE_PATTERN = re.compile(r"(?:공고번호\s*[:：]?\s*)?([A-Z0-9가-힣]+[-–][A-Z0-9가-힣-]{3,})")
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")


@dataclass(frozen=True)
class VariantConfig:
    name: str
    use_entity_score: bool
    use_type_weight: bool
    penalize_mismatch: bool
    max_chunks_per_doc: int
    dedupe_source_store: bool
    dedupe_evidence: bool
    metadata_weight: float
    type_weight: float
    target_weight: float
    preserve_top_n: int = 0


VARIANTS = [
    VariantConfig(
        name="A_current_96_baseline",
        use_entity_score=False,
        use_type_weight=False,
        penalize_mismatch=False,
        max_chunks_per_doc=5,
        dedupe_source_store=False,
        dedupe_evidence=False,
        metadata_weight=0.0,
        type_weight=0.0,
        target_weight=0.0,
        preserve_top_n=0,
    ),
    VariantConfig(
        name="B_entity_match_score",
        use_entity_score=True,
        use_type_weight=False,
        penalize_mismatch=False,
        max_chunks_per_doc=2,
        dedupe_source_store=False,
        dedupe_evidence=True,
        metadata_weight=0.35,
        type_weight=0.0,
        target_weight=0.25,
        preserve_top_n=0,
    ),
    VariantConfig(
        name="C_entity_score_redundancy_control",
        use_entity_score=True,
        use_type_weight=False,
        penalize_mismatch=True,
        max_chunks_per_doc=1,
        dedupe_source_store=True,
        dedupe_evidence=True,
        metadata_weight=0.45,
        type_weight=0.0,
        target_weight=0.30,
        preserve_top_n=2,
    ),
    VariantConfig(
        name="D_type_weighted_target_filter",
        use_entity_score=True,
        use_type_weight=True,
        penalize_mismatch=True,
        max_chunks_per_doc=1,
        dedupe_source_store=True,
        dedupe_evidence=True,
        metadata_weight=0.45,
        type_weight=0.30,
        target_weight=0.35,
        preserve_top_n=3,
    ),
    VariantConfig(
        name="E_conservative_preserve3_target_filter",
        use_entity_score=True,
        use_type_weight=True,
        penalize_mismatch=True,
        max_chunks_per_doc=1,
        dedupe_source_store=True,
        dedupe_evidence=True,
        metadata_weight=0.30,
        type_weight=0.20,
        target_weight=0.25,
        preserve_top_n=3,
    ),
]


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    run_dir = make_run_dir(Path(args.output_root), args.run_name)

    chunks = load_chunks_jsonl(args.chunks)
    issuer_aliases = build_issuer_aliases(chunks)
    target_extractor = TargetQueryExtractor(chunks, max_targets=args.target_max_count)

    eval_df = load_eval_csvs(Path(args.eval_dir), canonical_only=args.canonical_only)
    if args.ids:
        eval_df = eval_df[eval_df["id"].isin(args.ids)].copy()
    if args.limit and args.limit > 0:
        eval_df = eval_df.head(args.limit).copy()
    if eval_df.empty:
        raise SystemExit("No eval questions selected.")

    baseline_predictions = load_predictions_jsonl(Path(args.baseline_predictions))
    baseline_by_id = {row["id"]: row for row in baseline_predictions.to_dict(orient="records")}

    pipeline = build_candidate_pipeline(args)

    all_metric_rows: list[dict[str, Any]] = []
    all_question_rows: list[dict[str, Any]] = []
    jsonl_files = {variant.name: (run_dir / f"{variant.name}.jsonl").open("w", encoding="utf-8") for variant in VARIANTS}

    started = time.perf_counter()
    for idx, row in enumerate(eval_df.to_dict(orient="records"), start=1):
        question = str(row.get("question") or "")
        question_id = str(row.get("id") or "")
        question_type = classify_question(question)
        ground_truth_docs = row.get("ground_truth_doc_list") or []
        raw_metadata_filter = row.get("metadata_filter_obj") or parse_structured_cell(row.get("metadata_filter"), {})
        metadata_filter = resolve_eval_metadata_filter(
            raw_metadata_filter,
            question=question,
            issuer_aliases=issuer_aliases,
            expand_multi_agency_filter=args.expand_multi_agency_filter,
        )
        target_slots = extract_target_slots(
            question=question,
            metadata_filter=metadata_filter,
            raw_metadata_filter=raw_metadata_filter,
            target_extractor=target_extractor,
            issuer_aliases=issuer_aliases,
        )

        candidate_started = time.perf_counter()
        candidates = pipeline.retrieve(question, metadata_filter=metadata_filter)
        candidate_latency_ms = int((time.perf_counter() - candidate_started) * 1000)
        candidates = [format_context(rank, item, context_max_chars=args.context_max_chars) for rank, item in enumerate(candidates, 1)]

        baseline_contexts = (baseline_by_id.get(question_id) or {}).get("retrieved_contexts") or []
        variant_contexts = {
            "A_current_96_baseline": baseline_contexts[: args.top_k],
        }
        for variant in VARIANTS:
            if variant.name == "A_current_96_baseline":
                continue
            rescored = score_candidates(candidates, question, question_type, target_slots, variant)
            variant_contexts[variant.name] = select_with_redundancy(rescored, variant, top_k=args.top_k)

        for variant in VARIANTS:
            contexts = reassign_ranks(variant_contexts[variant.name])
            metrics = evaluate_contexts(ground_truth_docs, contexts, top_k=args.top_k)
            diagnostics = compute_diagnostics(contexts, target_slots, top_k=args.top_k)
            output_row = {
                "question_id": question_id,
                "question": question,
                "question_type": question_type,
                "variant_name": variant.name,
                "ground_truth_docs": ground_truth_docs,
                "retrieved_docs_top5": extract_top_unique_documents(contexts, top_k=args.top_k),
                "target_slots": target_slots,
                "retrieved_contexts": contexts,
                "metrics": metrics,
                "diagnostics": diagnostics,
                "metadata_filter": metadata_filter,
                "raw_metadata_filter": raw_metadata_filter,
                "candidate_count": len(candidates),
                "candidate_latency_ms": candidate_latency_ms,
            }
            jsonl_files[variant.name].write(json.dumps(output_row, ensure_ascii=False) + "\n")
            all_metric_rows.append({
                "question_id": question_id,
                "type": row.get("type"),
                "difficulty": row.get("difficulty"),
                "question_type": question_type,
                "variant_name": variant.name,
                **metrics,
                **diagnostics,
                "candidate_count": len(candidates),
                "candidate_latency_ms": candidate_latency_ms,
                "retrieved_docs_top5": json.dumps(output_row["retrieved_docs_top5"], ensure_ascii=False),
                "ground_truth_docs": json.dumps(ground_truth_docs, ensure_ascii=False),
            })
            all_question_rows.append(output_row)

        if args.progress_every and (idx == 1 or idx % args.progress_every == 0):
            print(f"[progress] {idx}/{len(eval_df)} processed {question_id}")

    for file in jsonl_files.values():
        file.close()

    elapsed_sec = time.perf_counter() - started
    per_question_csv = run_dir / "retrieval_target_filter_per_question_metrics.csv"
    summary_csv = run_dir / "retrieval_target_filter_metrics.csv"
    failure_csv = run_dir / "retrieval_target_filter_failure_examples.csv"
    analysis_md = run_dir / "retrieval_target_filter_summary.md"

    write_csv(per_question_csv, all_metric_rows)
    summary_rows = summarize_metrics(all_metric_rows)
    write_csv(summary_csv, summary_rows)
    failure_rows = build_failure_examples(all_metric_rows, limit=5)
    write_csv(failure_csv, failure_rows)
    write_summary_markdown(
        path=analysis_md,
        args=args,
        run_dir=run_dir,
        summary_rows=summary_rows,
        failure_rows=failure_rows,
        elapsed_sec=elapsed_sec,
        evaluated_questions=len(eval_df),
    )

    print_summary(summary_rows, failure_rows, run_dir, elapsed_sec)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run isolated retrieval target filtering experiments.")
    parser.add_argument("--eval-dir", default="data/eval")
    parser.add_argument("--canonical-only", action="store_true", default=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--baseline-predictions", default=DEFAULT_BASELINE)
    parser.add_argument("--chunks", default=DEFAULT_CHUNKS)
    parser.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)
    parser.add_argument("--output-root", default="outputs/retrieval_experiments")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--context-max-chars", type=int, default=1200)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--embedding-preset", default="kure")
    parser.add_argument("--vector-store", choices=["chroma", "faiss"], default="chroma")
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    parser.add_argument("--target-max-count", type=int, default=5)
    parser.add_argument("--expand-multi-agency-filter", action="store_true", default=False)
    return parser


def build_candidate_pipeline(args: argparse.Namespace) -> RAGPipeline:
    return RAGPipeline(
        chunk_path=args.chunks,
        retriever_type="dense",
        top_k=max(args.top_k, args.candidate_k),
        index_dir=args.index_dir,
        embedding_preset=args.embedding_preset,
        vector_store_type=args.vector_store,
        chroma_collection=args.chroma_collection,
        query_decomposition=True,
        decomposition_candidates_per_query=75,
        decomposition_selection="rrf",
        decomposition_conditional=True,
        decomposition_min_subqueries=2,
        document_scoring=True,
        doc_score_candidates=300,
        doc_score_method="mean_top_n",
        doc_score_top_n=3,
        doc_score_key="doc_id",
        target_aware=True,
        target_candidates=30,
        target_quota=1,
        target_min_count=2,
        target_max_count=5,
        target_base_preserve=3,
    )


def make_run_dir(output_root: Path, run_name: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base = run_name or datetime.now().strftime("target_filter_%Y%m%d_%H%M%S")
    run_dir = output_root / base
    suffix = 2
    while run_dir.exists():
        run_dir = output_root / f"{base}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def tokenize(value: Any) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(str(value or "")) if len(token) >= 2]


def extract_target_slots(
    question: str,
    metadata_filter: dict[str, Any],
    raw_metadata_filter: dict[str, Any],
    target_extractor: TargetQueryExtractor,
    issuer_aliases: list[tuple[str, set[str]]],
) -> dict[str, Any]:
    issuers = []
    for key in ("agency", "issuer"):
        value = metadata_filter.get(key) or raw_metadata_filter.get(key)
        if isinstance(value, list):
            issuers.extend(str(item) for item in value if item)
        elif value and str(value).strip().casefold() not in {"다중", "multi", "multiple"}:
            issuers.append(str(value))

    normalized_question = normalize_text(question)
    for issuer, aliases in issuer_aliases:
        if any(alias and alias in normalized_question for alias in aliases):
            issuers.append(issuer)

    target_queries = target_extractor.extract(question)
    years = sorted(set(YEAR_PATTERN.findall(question)))
    notices = sorted(set(match.group(1) for match in NOTICE_PATTERN.finditer(question)))
    quoted = re.findall(r"['\"‘’“”]([^'\"‘’“”]{4,80})['\"‘’“”]", question)

    project_terms = []
    for target in [*target_queries, *quoted]:
        project_terms.extend(tokenize(target))
    project_terms.extend(token for token in tokenize(question) if token not in {"사업", "문서", "기관", "예산", "기간", "얼마", "무엇"})

    return {
        "issuers": unique_list(issuers),
        "target_queries": unique_list(target_queries),
        "project_terms": unique_list(project_terms)[:30],
        "notice_numbers": notices,
        "years": years,
        "doc_name_hints": unique_list([*quoted, *target_queries])[:10],
    }


def score_candidates(
    candidates: list[dict[str, Any]],
    question: str,
    question_type: str,
    target_slots: dict[str, Any],
    variant: VariantConfig,
) -> list[dict[str, Any]]:
    base_scores = [_base_score(item, rank) for rank, item in enumerate(candidates, 1)]
    min_score = min(base_scores) if base_scores else 0.0
    max_score = max(base_scores) if base_scores else 1.0
    span = max(max_score - min_score, 1e-9)

    rescored = []
    for rank, item in enumerate(candidates, 1):
        copied = dict(item)
        base = (_base_score(item, rank) - min_score) / span
        entity_score, entity_reasons = entity_match_score(item, target_slots, penalize=variant.penalize_mismatch)
        type_score, type_reasons = question_type_score(item, question_type, question)
        target_score = target_query_score(item, target_slots)

        adjusted = base
        if variant.use_entity_score:
            adjusted += variant.metadata_weight * entity_score
            adjusted += variant.target_weight * target_score
        if variant.use_type_weight:
            adjusted += variant.type_weight * type_score

        copied["experiment_original_rank"] = rank
        copied["experiment_base_score"] = base
        copied["experiment_entity_score"] = entity_score
        copied["experiment_type_score"] = type_score
        copied["experiment_target_score"] = target_score
        copied["experiment_adjusted_score"] = adjusted
        copied["experiment_score_reasons"] = entity_reasons + type_reasons
        rescored.append(copied)

    return sorted(rescored, key=lambda item: float(item.get("experiment_adjusted_score") or 0.0), reverse=True)


def _base_score(item: dict[str, Any], rank: int) -> float:
    for key in ("doc_score", "target_best_score", "dense_score", "score"):
        value = item.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 1.0 / (60 + rank)


def entity_match_score(item: dict[str, Any], target_slots: dict[str, Any], penalize: bool) -> tuple[float, list[str]]:
    metadata = item.get("metadata") or {}
    issuer = str(metadata.get("issuer") or "")
    project_name = str(metadata.get("project_name") or "")
    source_file = str(metadata.get("source_file") or item.get("filename") or "")
    haystack = normalize_text(" ".join([issuer, project_name, source_file, str(item.get("text") or "")[:500]]))
    reasons = []
    score = 0.0

    issuers = target_slots.get("issuers") or []
    if issuers:
        issuer_match = any(normalize_text(expected) and normalize_text(expected) in normalize_text(issuer) for expected in issuers)
        if issuer_match:
            score += 1.0
            reasons.append("issuer_match")
        elif penalize:
            score -= 0.35
            reasons.append("issuer_mismatch")

    project_terms = [term for term in target_slots.get("project_terms") or [] if len(term) >= 2]
    if project_terms:
        item_terms = set(tokenize(" ".join([project_name, source_file])))
        overlap = len(set(project_terms) & item_terms)
        if overlap:
            score += min(1.0, overlap / max(3, len(set(project_terms))))
            reasons.append(f"project_overlap:{overlap}")
        elif penalize:
            score -= 0.10
            reasons.append("project_no_overlap")

    for notice in target_slots.get("notice_numbers") or []:
        if normalize_text(notice) and normalize_text(notice) in haystack:
            score += 1.0
            reasons.append("notice_match")

    for year in target_slots.get("years") or []:
        if year and year in haystack:
            score += 0.15
            reasons.append("year_match")

    return score, reasons


def target_query_score(item: dict[str, Any], target_slots: dict[str, Any]) -> float:
    metadata = item.get("metadata") or {}
    doc_text = " ".join(str(value or "") for value in [metadata.get("issuer"), metadata.get("project_name"), metadata.get("source_file")])
    doc_terms = set(tokenize(doc_text))
    best = 0.0
    for target in target_slots.get("target_queries") or []:
        target_terms = set(tokenize(target))
        if not target_terms:
            continue
        overlap = len(target_terms & doc_terms) / len(target_terms)
        best = max(best, overlap)
    return min(best, 1.0)


def question_type_score(item: dict[str, Any], question_type: str, question: str) -> tuple[float, list[str]]:
    if question_type == "general":
        return 0.0, []
    metadata = item.get("metadata") or {}
    text = " ".join(
        str(value or "")
        for value in [
            item.get("text"),
            metadata.get("section_path"),
            metadata.get("section_type"),
            metadata.get("chunk_type"),
            metadata.get("budget"),
            metadata.get("amounts"),
            metadata.get("dates"),
            metadata.get("exact_terms"),
        ]
    )
    normalized = text.casefold()
    keywords = QUESTION_TYPE_KEYWORDS.get(question_type, ())
    hits = [keyword for keyword in keywords if str(keyword).casefold() in normalized]
    if not hits:
        return 0.0, []
    return min(1.0, len(hits) / 3), [f"type_keyword:{keyword}" for keyword in hits[:5]]


def select_with_redundancy(candidates: list[dict[str, Any]], variant: VariantConfig, top_k: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    doc_counts: Counter[str] = Counter()
    seen_sources: set[str] = set()
    seen_evidence: set[str] = set()
    deferred: list[dict[str, Any]] = []

    if variant.preserve_top_n > 0:
        preserved = sorted(
            [item for item in candidates if int(item.get("experiment_original_rank") or 10**9) <= variant.preserve_top_n],
            key=lambda item: int(item.get("experiment_original_rank") or 10**9),
        )
        for item in preserved:
            if len(selected) >= top_k:
                return selected
            add_selected(item, selected, doc_counts, seen_sources, seen_evidence)

    for item in candidates:
        if variant.preserve_top_n > 0 and int(item.get("experiment_original_rank") or 10**9) <= variant.preserve_top_n:
            continue
        reason = redundancy_block_reason(item, variant, doc_counts, seen_sources, seen_evidence)
        if reason:
            copied = dict(item)
            copied["experiment_redundancy_skip_reason"] = reason
            deferred.append(copied)
            continue
        add_selected(item, selected, doc_counts, seen_sources, seen_evidence)
        if len(selected) >= top_k:
            return selected

    for item in deferred:
        doc_key = document_key(item)
        if doc_counts[doc_key] >= max(1, variant.max_chunks_per_doc):
            continue
        add_selected(item, selected, doc_counts, seen_sources, seen_evidence)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


def redundancy_block_reason(
    item: dict[str, Any],
    variant: VariantConfig,
    doc_counts: Counter[str],
    seen_sources: set[str],
    seen_evidence: set[str],
) -> str:
    doc_key = document_key(item)
    source_key = source_store_key(item)
    evidence_key = evidence_key_for(item)
    if doc_counts[doc_key] >= max(1, variant.max_chunks_per_doc):
        return "same_doc_limit"
    if variant.dedupe_source_store and source_key and source_key in seen_sources:
        return "duplicate_source_store_id"
    if variant.dedupe_evidence and evidence_key and evidence_key in seen_evidence:
        return "duplicate_evidence_id"
    return ""


def add_selected(item: dict[str, Any], selected: list[dict[str, Any]], doc_counts: Counter[str], seen_sources: set[str], seen_evidence: set[str]) -> None:
    copied = dict(item)
    doc_counts[document_key(copied)] += 1
    if source_store_key(copied):
        seen_sources.add(source_store_key(copied))
    if evidence_key_for(copied):
        seen_evidence.add(evidence_key_for(copied))
    selected.append(copied)


def document_key(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    return str(item.get("doc_id") or metadata.get("doc_id") or metadata.get("source_file") or item.get("filename") or item.get("chunk_id") or "")


def source_store_key(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    return str(metadata.get("source_store_id") or item.get("source_store_id") or "")


def evidence_key_for(item: dict[str, Any]) -> str:
    return str(item.get("evidence_id") or item.get("chunk_id") or "")


def reassign_ranks(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for rank, item in enumerate(contexts, 1):
        copied = dict(item)
        copied["rank"] = rank
        ranked.append(copied)
    return ranked


def evaluate_contexts(ground_truth_docs: list[str], contexts: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    retrieved_docs = extract_top_unique_documents(contexts, top_k=top_k)
    metric_1 = compute_retrieval_metrics(ground_truth_docs, retrieved_docs, top_k=1)
    metric_3 = compute_retrieval_metrics(ground_truth_docs, retrieved_docs, top_k=3)
    metric_5 = compute_retrieval_metrics(ground_truth_docs, retrieved_docs, top_k=top_k)
    recall = compute_doc_recall_metrics(ground_truth_docs, retrieved_docs, top_k=top_k)
    return {
        "hit_at_1": metric_1["hit_at_5"],
        "hit_at_3": metric_3["hit_at_5"],
        "hit_at_5": metric_5["hit_at_5"],
        "mrr_at_5": metric_5["mrr_at_5"],
        "ndcg_at_5": metric_5["ndcg_at_5"],
        **recall,
        "first_relevant_rank": first_relevant_rank(ground_truth_docs, retrieved_docs),
        "contains_any_answer_doc": 1.0 if recall.get("matched_doc_count", 0) else 0.0,
    }


def compute_diagnostics(contexts: list[dict[str, Any]], target_slots: dict[str, Any], top_k: int) -> dict[str, Any]:
    top_contexts = contexts[:top_k]
    doc_keys = [document_key(item) for item in top_contexts]
    duplicate_doc_count = len(doc_keys) - len(set(doc_keys))
    source_keys = [source_store_key(item) for item in top_contexts if source_store_key(item)]
    duplicate_source_store_count = len(source_keys) - len(set(source_keys))
    mismatch_count = 0
    checked = 0
    expected_issuers = [normalize_text(value) for value in target_slots.get("issuers") or [] if normalize_text(value)]
    if expected_issuers:
        for item in top_contexts:
            issuer = normalize_text((item.get("metadata") or {}).get("issuer"))
            if issuer:
                checked += 1
                if not any(expected in issuer or issuer in expected for expected in expected_issuers):
                    mismatch_count += 1
    return {
        "unique_doc_count_top5": len(set(doc_keys)),
        "duplicate_doc_count_top5": duplicate_doc_count,
        "duplicate_source_store_count_top5": duplicate_source_store_count,
        "target_mismatch_count_top5": mismatch_count,
        "target_mismatch_rate_top5": mismatch_count / checked if checked else math.nan,
    }


def summarize_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["variant_name"]].append(row)

    summary = []
    metric_names = [
        "hit_at_1", "hit_at_3", "hit_at_5", "mrr_at_5", "ndcg_at_5", "doc_recall_at_5",
        "multi_doc_recall_at_5", "contains_any_answer_doc", "unique_doc_count_top5",
        "duplicate_doc_count_top5", "duplicate_source_store_count_top5", "target_mismatch_rate_top5",
        "candidate_latency_ms",
    ]
    baseline = None
    for variant, items in grouped.items():
        row = {"variant_name": variant, "num_questions": len(items)}
        for metric in metric_names:
            values = [float(item[metric]) for item in items if item.get(metric) not in (None, "") and not is_nan(item.get(metric))]
            row[metric] = sum(values) / len(values) if values else math.nan
        summary.append(row)
        if variant == "A_current_96_baseline":
            baseline = row

    if baseline:
        for row in summary:
            row["delta_ndcg_vs_baseline"] = safe_delta(row.get("ndcg_at_5"), baseline.get("ndcg_at_5"))
            row["delta_hit5_vs_baseline"] = safe_delta(row.get("hit_at_5"), baseline.get("hit_at_5"))
            row["delta_multi_doc_recall_vs_baseline"] = safe_delta(row.get("multi_doc_recall_at_5"), baseline.get("multi_doc_recall_at_5"))
    return sorted(summary, key=lambda item: (item.get("ndcg_at_5") if not is_nan(item.get("ndcg_at_5")) else -1), reverse=True)


def build_failure_examples(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    grouped_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_by_question: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped_by_variant[row["variant_name"]].append(row)
        grouped_by_question[row["question_id"]][row["variant_name"]] = row

    candidate_variants = [name for name in grouped_by_variant if name != "A_current_96_baseline"]
    if not candidate_variants:
        return []

    def avg_ndcg(variant_name: str) -> float:
        values = [float(row["ndcg_at_5"]) for row in grouped_by_variant[variant_name] if not is_nan(row.get("ndcg_at_5"))]
        return sum(values) / len(values) if values else -1.0

    best_variant = max(candidate_variants, key=avg_ndcg)
    examples = []
    for question_id, by_variant in grouped_by_question.items():
        baseline = by_variant.get("A_current_96_baseline")
        row = by_variant.get(best_variant)
        if not baseline or not row:
            continue
        if float(row.get("hit_at_5") or 0.0) < 1.0 or float(row.get("ndcg_at_5") or 0.0) < 1.0:
            examples.append({
                "question_id": question_id,
                "variant_name": best_variant,
                "baseline_hit_at_5": baseline.get("hit_at_5"),
                "variant_hit_at_5": row.get("hit_at_5"),
                "baseline_ndcg_at_5": baseline.get("ndcg_at_5"),
                "variant_ndcg_at_5": row.get("ndcg_at_5"),
                "ground_truth_docs": row.get("ground_truth_docs"),
                "retrieved_docs_top5": row.get("retrieved_docs_top5"),
            })
    examples.sort(key=lambda item: (float(item["variant_hit_at_5"]), float(item["variant_ndcg_at_5"]), item["question_id"]))
    return examples[:limit]

def write_summary_markdown(
    path: Path,
    args: argparse.Namespace,
    run_dir: Path,
    summary_rows: list[dict[str, Any]],
    failure_rows: list[dict[str, Any]],
    elapsed_sec: float,
    evaluated_questions: int,
) -> None:
    lines = [
        "# Retrieval Target Filter Experiment",
        "",
        "## Existing Implementations Reused",
        "",
        "- dense retrieval: `src/retriever/dense.py`, `src/pipeline/rag_pipeline.py`",
        "- hybrid search: `src/retriever/hybrid.py`",
        "- rerank: `src/retriever/rerank.py`",
        "- query decomposition: `src/retriever/query_decomposition.py`",
        "- metadata filtering: `src/retriever/metadata_filter.py`, `scripts/generate_eval_predictions.py`",
        "- document diversity: `src/retriever/diversity.py`",
        "- document scoring: `src/retriever/document_score.py`",
        "- target-aware selection: `src/retriever/target_aware.py`",
        "- Chroma/FAISS: `src/vectorstore/chroma_store.py`, `src/vectorstore/faiss_store.py`",
        "",
        "No production retrieval module was overwritten. This experiment only applies an isolated selector on top of retrieved candidates.",
        "",
        "## Run Config",
        "",
        f"- evaluated_questions: {evaluated_questions}",
        f"- candidate_k: {args.candidate_k}",
        f"- baseline_predictions: `{args.baseline_predictions}`",
        f"- output_dir: `{run_dir}`",
        f"- elapsed_sec: {elapsed_sec:.1f}",
        "",
        "## Summary Metrics",
        "",
        markdown_table(summary_rows),
        "",
        "## Failure Examples",
        "",
        markdown_table(failure_rows) if failure_rows else "No failure examples found.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, float):
                value = "" if math.isnan(value) else f"{value:.4f}"
            text = str(value).replace("|", "/").replace("\n", " ")
            values.append(text[:180])
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_summary(summary_rows: list[dict[str, Any]], failure_rows: list[dict[str, Any]], run_dir: Path, elapsed_sec: float) -> None:
    print("\n[SUMMARY]")
    for row in summary_rows:
        print(
            f"{row['variant_name']}: "
            f"hit5={fmt(row.get('hit_at_5'))} "
            f"mrr={fmt(row.get('mrr_at_5'))} "
            f"ndcg={fmt(row.get('ndcg_at_5'))} "
            f"multi_recall={fmt(row.get('multi_doc_recall_at_5'))} "
            f"dup_docs={fmt(row.get('duplicate_doc_count_top5'))} "
            f"target_mismatch={fmt(row.get('target_mismatch_rate_top5'))}"
        )
    print(f"elapsed_sec={elapsed_sec:.1f}")
    print(f"outputs={run_dir}")
    if failure_rows:
        print("\n[FAILURE EXAMPLES]")
        for row in failure_rows:
            print(f"- {row['question_id']} {row['variant_name']} hit {row['baseline_hit_at_5']} -> {row['variant_hit_at_5']}")


def safe_delta(value: Any, baseline: Any) -> float:
    if is_nan(value) or is_nan(baseline):
        return math.nan
    return float(value) - float(baseline)


def is_nan(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def fmt(value: Any) -> str:
    if is_nan(value):
        return "nan"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def unique_list(values: list[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = normalize_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
