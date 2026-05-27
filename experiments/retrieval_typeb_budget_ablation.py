#!/usr/bin/env python3
"""Ablation experiments for type-B budget retrieval improvements.

This file does not modify production retrieval code. It reuses the existing
candidate pipeline and applies experimental selectors only for type-B budget
questions. Outputs are isolated under outputs/retrieval_experiments/<run_name>/.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
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

from rag_eval.loaders import load_eval_csvs
from rag_eval.normalization import extract_top_unique_documents, parse_structured_cell
from scripts.generate_eval_predictions import build_issuer_aliases, format_context, resolve_eval_metadata_filter
from src.data import load_chunks_jsonl
from src.generation.context_builder import classify_question
from src.retriever.target_aware import TargetQueryExtractor

import retrieval_target_filter_experiment as base

FEATURES = {
    "1": "enhanced_target_extraction",
    "2": "similar_project_suppression",
    "3": "typeb_budget_target_quota",
    "4": "doc_then_chunk_selection",
    "5": "canonical_doc_grouping",
}
TYPEB_BUDGET_TYPES = {"B"}
BUDGET_QUERY_TYPES = {"budget"}
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
NOISE_TOKENS = {
    "사업", "문서", "기관", "예산", "금액", "사업비", "규모", "얼마", "각각", "비교", "알려", "주세요",
    "정보", "시스템", "구축", "용역", "공고", "입찰", "제안", "요청", "통합", "차세대",
}
VERSION_NOISE_PATTERN = re.compile(
    r"재공고|긴급|사전공개|지문|국제|국내|공고|입찰|제안요청서|제안요청|과업지시서|용역|사업|구축|시스템|차세대|고도화|운영|유지관리|\d+차|1차|2차",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AblationVariant:
    name: str
    features: tuple[str, ...]


def main() -> int:
    args = build_arg_parser().parse_args()
    run_dir = make_run_dir(Path(args.output_root), args.run_name)

    chunks = load_chunks_jsonl(args.chunks)
    issuer_aliases = build_issuer_aliases(chunks)
    target_extractor = TargetQueryExtractor(chunks, max_targets=args.target_max_count)
    eval_df = load_eval_csvs(Path(args.eval_dir), canonical_only=True)
    if args.limit:
        eval_df = eval_df.head(args.limit).copy()

    pipeline = base.build_candidate_pipeline(args)
    variants = build_variants()
    all_metrics: list[dict[str, Any]] = []
    topdoc_rows: list[dict[str, Any]] = []
    full_records_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)

    started = time.perf_counter()
    for idx, row in enumerate(eval_df.to_dict(orient="records"), start=1):
        question_id = str(row.get("id") or "")
        question = str(row.get("question") or "")
        eval_type = str(row.get("type") or "").strip().upper()
        question_type = classify_question(question)
        is_focus = eval_type in TYPEB_BUDGET_TYPES and question_type in BUDGET_QUERY_TYPES
        ground_truth_docs = row.get("ground_truth_doc_list") or []
        raw_metadata_filter = row.get("metadata_filter_obj") or parse_structured_cell(row.get("metadata_filter"), {})
        metadata_filter = resolve_eval_metadata_filter(
            raw_metadata_filter,
            question=question,
            issuer_aliases=issuer_aliases,
            expand_multi_agency_filter=args.expand_multi_agency_filter,
        )

        target_slots = base.extract_target_slots(
            question=question,
            metadata_filter=metadata_filter,
            raw_metadata_filter=raw_metadata_filter,
            target_extractor=target_extractor,
            issuer_aliases=issuer_aliases,
        )

        candidate_started = time.perf_counter()
        raw_candidates = pipeline.retrieve(question, metadata_filter=metadata_filter)
        candidate_latency_ms = int((time.perf_counter() - candidate_started) * 1000)
        candidates = [base.format_context(rank, item, context_max_chars=args.context_max_chars) for rank, item in enumerate(raw_candidates, 1)]

        for variant in variants:
            contexts = apply_variant(candidates, question, question_type, eval_type, target_slots, variant, args.top_k)
            metrics = base.evaluate_contexts(ground_truth_docs, contexts, top_k=args.top_k)
            diagnostics = base.compute_diagnostics(contexts, target_slots, top_k=args.top_k)
            top_docs = extract_top_unique_documents(contexts, top_k=args.top_k)
            metric_row = {
                "question_id": question_id,
                "type": eval_type,
                "difficulty": row.get("difficulty"),
                "question_type": question_type,
                "is_focus_typeb_budget": is_focus,
                "variant_name": variant.name,
                "features": "+".join(variant.features) if variant.features else "base_D",
                **metrics,
                **diagnostics,
                "candidate_latency_ms": candidate_latency_ms,
                "retrieved_docs_top5": json.dumps(top_docs, ensure_ascii=False),
                "ground_truth_docs": json.dumps(ground_truth_docs, ensure_ascii=False),
            }
            all_metrics.append(metric_row)
            topdoc_rows.append({
                "question_id": question_id,
                "variant_name": variant.name,
                "features": metric_row["features"],
                "is_focus_typeb_budget": is_focus,
                "hit_at_5": metrics.get("hit_at_5"),
                "ndcg_at_5": metrics.get("ndcg_at_5"),
                "retrieved_docs_top5": top_docs,
                "ground_truth_docs": ground_truth_docs,
            })
            full_records_by_variant[variant.name].append({
                "question_id": question_id,
                "question": question,
                "type": eval_type,
                "question_type": question_type,
                "variant_name": variant.name,
                "features": metric_row["features"],
                "is_focus_typeb_budget": is_focus,
                "target_slots": target_slots,
                "ground_truth_docs": ground_truth_docs,
                "retrieved_docs_top5": top_docs,
                "retrieved_contexts": contexts,
                "metrics": metrics,
                "diagnostics": diagnostics,
            })

        if args.progress_every and (idx == 1 or idx % args.progress_every == 0):
            print(f"[progress] {idx}/{len(eval_df)} processed {question_id}")

    summary = summarize(all_metrics)
    best = max(summary, key=lambda row: (row["ndcg_at_5"], row["hit_at_5"], row["multi_doc_recall_at_5"]))
    elapsed_sec = time.perf_counter() - started

    write_csv(run_dir / "typeb_budget_ablation_per_question_metrics.csv", all_metrics)
    write_csv(run_dir / "typeb_budget_ablation_metrics.csv", summary)
    write_jsonl(run_dir / "typeb_budget_ablation_topdocs.jsonl", topdoc_rows)
    write_jsonl(run_dir / "best_variant_predictions.jsonl", full_records_by_variant[best["variant_name"]])
    failure_rows = build_failure_examples(all_metrics, best["variant_name"], limit=5)
    write_csv(run_dir / "best_variant_failure_examples.csv", failure_rows)
    write_summary(run_dir, args, summary, best, failure_rows, elapsed_sec)

    print_summary(summary, best, failure_rows, run_dir, elapsed_sec)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run type-B budget retrieval ablation experiments.")
    parser.add_argument("--eval-dir", default="data/eval")
    parser.add_argument("--chunks", default=base.DEFAULT_CHUNKS)
    parser.add_argument("--index-dir", default=base.DEFAULT_INDEX_DIR)
    parser.add_argument("--output-root", default="outputs/retrieval_experiments")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--context-max-chars", type=int, default=1200)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--embedding-preset", default="kure")
    parser.add_argument("--vector-store", choices=["chroma", "faiss"], default="chroma")
    parser.add_argument("--chroma-collection", default="rfp_chunks")
    parser.add_argument("--target-max-count", type=int, default=5)
    parser.add_argument("--expand-multi-agency-filter", action="store_true", default=False)
    return parser


def build_variants() -> list[AblationVariant]:
    variants = [AblationVariant("base_D_current", tuple())]
    for key, name in FEATURES.items():
        variants.append(AblationVariant(f"F{key}_{name}", (key,)))
    keys = tuple(FEATURES.keys())
    for size in range(2, len(keys) + 1):
        for combo in itertools.combinations(keys, size):
            label = "".join(combo)
            variants.append(AblationVariant(f"C{label}_" + "_".join(FEATURES[key].split("_")[0] for key in combo), combo))
    return variants


def make_run_dir(output_root: Path, run_name: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base_name = run_name or datetime.now().strftime("typeb_budget_ablation_%Y%m%d_%H%M%S")
    run_dir = output_root / base_name
    suffix = 2
    while run_dir.exists():
        run_dir = output_root / f"{base_name}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


def apply_variant(
    candidates: list[dict[str, Any]],
    question: str,
    question_type: str,
    eval_type: str,
    target_slots: dict[str, Any],
    variant: AblationVariant,
    top_k: int,
) -> list[dict[str, Any]]:
    focus = eval_type in TYPEB_BUDGET_TYPES and question_type in BUDGET_QUERY_TYPES
    active_slots = enhance_target_slots(question, target_slots) if focus and "1" in variant.features else target_slots
    scored = base.score_candidates(candidates, question, question_type, active_slots, base.VARIANTS[3])

    if not focus or not variant.features:
        return base.reassign_ranks(base.select_with_redundancy(scored, base.VARIANTS[3], top_k=top_k))

    if "4" in variant.features:
        scored = doc_then_chunk_candidates(scored, question_type)

    selected = select_featured(scored, active_slots, variant.features, top_k)
    return base.reassign_ranks(selected)


def enhance_target_slots(question: str, target_slots: dict[str, Any]) -> dict[str, Any]:
    enhanced = {key: list(value) if isinstance(value, list) else value for key, value in target_slots.items()}
    prefix = re.split(r"예산|사업비|금액|규모|얼마", question, maxsplit=1)[0]
    raw_parts = re.split(r"[,，、;]|\s+및\s+|\s+그리고\s+", prefix)
    fragments = []
    for part in raw_parts:
        cleaned = clean_fragment(part)
        if looks_like_target(cleaned):
            fragments.append(cleaned)
    fragments = unique_list([*fragments, *(enhanced.get("target_queries") or [])])[:8]
    enhanced["target_queries"] = fragments
    project_terms = list(enhanced.get("project_terms") or [])
    for fragment in fragments:
        project_terms.extend(token for token in tokenize(fragment) if token not in NOISE_TOKENS)
    enhanced["project_terms"] = unique_list(project_terms)[:40]
    enhanced["enhanced_target_count"] = len(fragments)
    return enhanced


def clean_fragment(text: str) -> str:
    text = re.sub(r"^[\s\-•*0-9.)①-⑳]+", "", str(text or "").strip())
    text = re.sub(r"^(그리고|또한|아울러|각각|전체|다음|다음의)\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;·/은는이가을를의")


def looks_like_target(text: str) -> bool:
    if len(text) < 8:
        return False
    tokens = tokenize(text)
    if len(tokens) < 2:
        return False
    signals = ("공사", "공단", "재단", "연구원", "대학교", "KOICA", "코이카", "시스템", "플랫폼", "센터", "사업", "구축")
    return any(signal.casefold() in text.casefold() for signal in signals)


def select_featured(candidates: list[dict[str, Any]], target_slots: dict[str, Any], features: tuple[str, ...], top_k: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    doc_counts: Counter[str] = Counter()
    seen_sources: set[str] = set()
    seen_evidence: set[str] = set()
    seen_canonical: set[str] = set()

    preserve_n = 2 if "3" in features else 3
    for item in sorted(candidates, key=lambda x: int(x.get("experiment_original_rank") or 10**9)):
        if int(item.get("experiment_original_rank") or 10**9) > preserve_n:
            continue
        add_featured(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical)
        if len(selected) >= top_k:
            return selected

    if "3" in features:
        for item in quota_candidates(candidates, target_slots, selected):
            if len(selected) >= top_k:
                return selected
            if block_reason(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical, features):
                continue
            add_featured(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical)

    deferred = []
    for item in candidates:
        if item in selected:
            continue
        reason = block_reason(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical, features)
        if reason:
            deferred.append(item)
            continue
        add_featured(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical)
        if len(selected) >= top_k:
            return selected

    for item in deferred:
        if len(selected) >= top_k:
            break
        if base.document_key(item) in {base.document_key(s) for s in selected}:
            continue
        add_featured(item, selected, doc_counts, seen_sources, seen_evidence, seen_canonical)
    return selected[:top_k]


def quota_candidates(candidates: list[dict[str, Any]], target_slots: dict[str, Any], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    selected_docs = {base.document_key(item) for item in selected}
    for target in target_slots.get("target_queries") or []:
        target_terms = set(token for token in tokenize(target) if token not in NOISE_TOKENS)
        if not target_terms:
            continue
        scored = []
        for item in candidates:
            if base.document_key(item) in selected_docs:
                continue
            doc_terms = doc_term_set(item)
            overlap = len(target_terms & doc_terms) / max(1, len(target_terms))
            if overlap < 0.18:
                continue
            score = overlap + 0.15 * float(item.get("experiment_type_score") or 0.0) + 0.05 * float(item.get("experiment_adjusted_score") or 0.0)
            scored.append((score, item))
        if scored:
            scored.sort(key=lambda pair: pair[0], reverse=True)
            output.append(scored[0][1])
            selected_docs.add(base.document_key(scored[0][1]))
    return output


def block_reason(
    item: dict[str, Any],
    selected: list[dict[str, Any]],
    doc_counts: Counter[str],
    seen_sources: set[str],
    seen_evidence: set[str],
    seen_canonical: set[str],
    features: tuple[str, ...],
) -> str:
    doc_key = base.document_key(item)
    if doc_counts[doc_key] >= 1:
        return "same_doc_limit"
    source = base.source_store_key(item)
    if source and source in seen_sources:
        return "duplicate_source_store_id"
    evidence = base.evidence_key_for(item)
    if evidence and evidence in seen_evidence:
        return "duplicate_evidence_id"
    if "2" in features and any(is_similar_project(item, other) for other in selected):
        return "similar_project_suppressed"
    canonical = canonical_group(item)
    if "5" in features and canonical and canonical in seen_canonical:
        return "canonical_group_duplicate"
    return ""


def add_featured(
    item: dict[str, Any],
    selected: list[dict[str, Any]],
    doc_counts: Counter[str],
    seen_sources: set[str],
    seen_evidence: set[str],
    seen_canonical: set[str],
) -> None:
    copied = dict(item)
    doc_counts[base.document_key(copied)] += 1
    if base.source_store_key(copied):
        seen_sources.add(base.source_store_key(copied))
    if base.evidence_key_for(copied):
        seen_evidence.add(base.evidence_key_for(copied))
    group = canonical_group(copied)
    if group:
        seen_canonical.add(group)
    selected.append(copied)


def doc_then_chunk_candidates(candidates: list[dict[str, Any]], question_type: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[base.document_key(item)].append(item)
    representatives = []
    for items in grouped.values():
        for item in items:
            item["experiment_doc_then_chunk_score"] = float(item.get("experiment_adjusted_score") or 0.0) + 0.15 * float(item.get("experiment_type_score") or 0.0)
        representatives.append(max(items, key=lambda x: float(x.get("experiment_doc_then_chunk_score") or 0.0)))
    return sorted(representatives, key=lambda x: float(x.get("experiment_doc_then_chunk_score") or 0.0), reverse=True)


def is_similar_project(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_meta = left.get("metadata") or {}
    right_meta = right.get("metadata") or {}
    if normalize(left_meta.get("issuer")) != normalize(right_meta.get("issuer")):
        return False
    lt = project_tokens(left)
    rt = project_tokens(right)
    if not lt or not rt:
        return False
    jaccard = len(lt & rt) / len(lt | rt)
    return jaccard >= 0.72


def canonical_group(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    issuer = normalize(metadata.get("issuer"))
    text = str(metadata.get("project_name") or metadata.get("source_file") or item.get("filename") or "")
    text = VERSION_NOISE_PATTERN.sub(" ", text)
    tokens = [token for token in tokenize(text) if token not in NOISE_TOKENS and len(token) >= 2]
    return issuer + "::" + " ".join(tokens[:8])


def project_tokens(item: dict[str, Any]) -> set[str]:
    metadata = item.get("metadata") or {}
    text = " ".join(str(v or "") for v in [metadata.get("project_name"), metadata.get("source_file"), item.get("filename")])
    return {token for token in tokenize(VERSION_NOISE_PATTERN.sub(" ", text)) if token not in NOISE_TOKENS and len(token) >= 2}


def doc_term_set(item: dict[str, Any]) -> set[str]:
    metadata = item.get("metadata") or {}
    text = " ".join(str(v or "") for v in [metadata.get("issuer"), metadata.get("project_name"), metadata.get("source_file"), item.get("filename")])
    return {token for token in tokenize(text) if token not in NOISE_TOKENS}


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def tokenize(value: Any) -> list[str]:
    return [token.casefold() for token in TOKEN_PATTERN.findall(str(value or "")) if len(token) >= 2]


def unique_list(values: list[Any]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = normalize(text)
        if text and key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["variant_name"]].append(row)
    metrics = [
        "hit_at_1", "hit_at_3", "hit_at_5", "mrr_at_5", "ndcg_at_5", "doc_recall_at_5",
        "multi_doc_recall_at_5", "target_mismatch_rate_top5", "duplicate_doc_count_top5",
    ]
    summary = []
    base_row = None
    for variant, items in grouped.items():
        row = {
            "variant_name": variant,
            "features": items[0]["features"],
            "num_questions": len(items),
            "focus_questions": sum(bool(item["is_focus_typeb_budget"]) for item in items),
        }
        for metric in metrics:
            values = [float(item[metric]) for item in items if item.get(metric) not in (None, "") and not is_nan(item.get(metric))]
            row[metric] = sum(values) / len(values) if values else math.nan
            focus_values = [float(item[metric]) for item in items if item.get("is_focus_typeb_budget") and item.get(metric) not in (None, "") and not is_nan(item.get(metric))]
            row[f"focus_{metric}"] = sum(focus_values) / len(focus_values) if focus_values else math.nan
        summary.append(row)
        if variant == "base_D_current":
            base_row = row
    if base_row:
        for row in summary:
            for metric in ["hit_at_5", "ndcg_at_5", "multi_doc_recall_at_5", "focus_hit_at_5", "focus_ndcg_at_5", "focus_multi_doc_recall_at_5"]:
                row[f"delta_{metric}"] = safe_delta(row.get(metric), base_row.get(metric))
    return sorted(summary, key=lambda r: (r["ndcg_at_5"], r["hit_at_5"], r.get("multi_doc_recall_at_5", -1)), reverse=True)


def build_failure_examples(rows: list[dict[str, Any]], best_variant: str, limit: int = 5) -> list[dict[str, Any]]:
    grouped = defaultdict(dict)
    for row in rows:
        grouped[row["question_id"]][row["variant_name"]] = row
    failures = []
    for qid, variants in grouped.items():
        row = variants.get(best_variant)
        base_row = variants.get("base_D_current")
        if not row or not base_row:
            continue
        if row["hit_at_5"] < 1 or row["ndcg_at_5"] < 1:
            failures.append({
                "question_id": qid,
                "type": row.get("type"),
                "difficulty": row.get("difficulty"),
                "question_type": row.get("question_type"),
                "base_hit_at_5": base_row.get("hit_at_5"),
                "best_hit_at_5": row.get("hit_at_5"),
                "base_ndcg_at_5": base_row.get("ndcg_at_5"),
                "best_ndcg_at_5": row.get("ndcg_at_5"),
                "ground_truth_docs": row.get("ground_truth_docs"),
                "retrieved_docs_top5": row.get("retrieved_docs_top5"),
            })
    failures.sort(key=lambda r: (float(r["best_hit_at_5"]), float(r["best_ndcg_at_5"]), r["question_id"]))
    return failures[:limit]


def write_summary(run_dir: Path, args: argparse.Namespace, summary: list[dict[str, Any]], best: dict[str, Any], failures: list[dict[str, Any]], elapsed_sec: float) -> None:
    path = run_dir / "typeb_budget_ablation_summary.md"
    lines = [
        "# Type-B Budget Retrieval Ablation",
        "",
        "This experiment tests five focused improvements on top of the previous D variant.",
        "Production retrieval files and previous outputs were not overwritten.",
        "",
        "## Features",
        "",
        "1. enhanced target extraction",
        "2. similar project suppression",
        "3. type-B budget target quota",
        "4. document-then-chunk selection",
        "5. canonical document grouping",
        "",
        "## Run Config",
        "",
        f"- candidate_k: {args.candidate_k}",
        f"- elapsed_sec: {elapsed_sec:.1f}",
        f"- output_dir: `{run_dir}`",
        "",
        "## Best Variant",
        "",
        f"- variant: `{best['variant_name']}`",
        f"- features: `{best['features']}`",
        f"- hit@5: {best['hit_at_5']:.4f}",
        f"- nDCG@5: {best['ndcg_at_5']:.4f}",
        f"- multi-doc recall@5: {best['multi_doc_recall_at_5']:.4f}",
        f"- focus type-B budget hit@5: {best['focus_hit_at_5']:.4f}",
        f"- focus type-B budget nDCG@5: {best['focus_ndcg_at_5']:.4f}",
        "",
        "## Summary Metrics",
        "",
        markdown_table(summary),
        "",
        "## Best Variant Failure Examples",
        "",
        markdown_table(failures),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        values = []
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, float):
                val = "" if math.isnan(val) else f"{val:.4f}"
            values.append(str(val).replace("|", "/").replace("\n", " ")[:180])
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_summary(summary: list[dict[str, Any]], best: dict[str, Any], failures: list[dict[str, Any]], run_dir: Path, elapsed_sec: float) -> None:
    print("\n[SUMMARY TOP 10]")
    for row in summary[:10]:
        print(
            f"{row['variant_name']}: ndcg={row['ndcg_at_5']:.4f} hit5={row['hit_at_5']:.4f} "
            f"multi={row['multi_doc_recall_at_5']:.4f} focus_ndcg={row['focus_ndcg_at_5']:.4f} "
            f"features={row['features']}"
        )
    print(f"\n[BEST] {best['variant_name']} features={best['features']}")
    print(f"outputs={run_dir}")
    print(f"elapsed_sec={elapsed_sec:.1f}")
    if failures:
        print("\n[FAILURE EXAMPLES]")
        for row in failures:
            print(f"- {row['question_id']} hit={row['best_hit_at_5']} ndcg={row['best_ndcg_at_5']}")


def safe_delta(value: Any, baseline: Any) -> float:
    if is_nan(value) or is_nan(baseline):
        return math.nan
    return float(value) - float(baseline)


def is_nan(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
