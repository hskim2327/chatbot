from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evidence_recall_diagnostics as recall_diag
import evidence_selection_experiment as base


DEFAULT_OUTPUT_DIR = Path("outputs/evidence_recall/evidence_selection_expanded_experiment")
DEFAULT_SOURCE_STORE = Path("data/processed/source_store_v2_125.jsonl")

STOPWORDS = {
    "사업",
    "용역",
    "구축",
    "관련",
    "예산",
    "금액",
    "기간",
    "제출",
    "서류",
    "무엇",
    "어떤",
    "얼마",
    "입니까",
    "인가요",
    "알려",
    "주세요",
    "그리고",
}

SOURCE_FINAL_FIELDS = (
    "final_budget",
    "final_budget_krw",
    "final_budget_status",
    "final_budget_type",
    "final_project_duration",
    "final_maintenance_period",
    "final_warranty_period",
    "final_deadline_terms",
    "final_bid_deadline",
    "bid_deadline_status",
)


def load_source_store(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            source_store_id = str(row.get("source_store_id") or "")
            if source_store_id:
                index[source_store_id] = row
    return index


def source_store_id(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    source_ref = chunk.get("source_ref") if isinstance(chunk.get("source_ref"), dict) else {}
    return str(source_ref.get("source_store_id") or metadata.get("source_store_id") or "")


def source_record_for_chunk(
    chunk: dict[str, Any],
    source_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return source_index.get(source_store_id(chunk), {})


def load_doc_profiles(chunks: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    profiles: dict[str, dict[str, Any]] = {}
    alias_to_primary: dict[str, str] = {}

    for chunk in chunks:
        source_file = base.chunk_source_file(chunk)
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        primary = base.normalize_doc_key(source_file or chunk.get("doc_id"))
        if not primary:
            continue
        profile = profiles.setdefault(
            primary,
            {
                "doc_key": primary,
                "source_file": source_file,
                "doc_ids": set(),
                "issuers": set(),
                "project_names": set(),
                "aliases": set(),
                "summary_texts": [],
                "chunks": [],
            },
        )
        profile["chunks"].append(chunk)
        if chunk.get("doc_id"):
            profile["doc_ids"].add(str(chunk.get("doc_id")))
        for key in base.chunk_doc_keys(chunk):
            profile["aliases"].add(key)
            alias_to_primary[key] = primary
        for value in (metadata.get("issuer"), metadata.get("project_name"), metadata.get("doc_key"), source_file):
            key = base.normalize_doc_key(value)
            if key:
                profile["aliases"].add(key)
                alias_to_primary[key] = primary
        if metadata.get("issuer"):
            profile["issuers"].add(str(metadata.get("issuer")))
        if metadata.get("project_name"):
            profile["project_names"].add(str(metadata.get("project_name")))
        if base.chunk_fact_type(chunk) in {"document_summary", "document_identity"}:
            profile["summary_texts"].append(str(chunk.get("text") or "")[:1000])

    return profiles, alias_to_primary


def compact(value: Any) -> str:
    return base.normalize_doc_key(value)


def question_terms(question: str) -> list[str]:
    terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", question or "")
    result = []
    for term in terms:
        if term in STOPWORDS:
            continue
        if len(term) < 2:
            continue
        result.append(term)
    return base.unique_keep_order(result)[:30]


def quoted_targets(question: str) -> list[str]:
    targets = re.findall(r"[\"'“”‘’「」『』](.*?)[\"'“”‘’「」『』]", question or "")
    targets.extend(re.findall(r"'([^']+)'", question or ""))
    return [target.strip() for target in targets if len(target.strip()) >= 3]


def profile_match_text(profile: dict[str, Any]) -> str:
    values = [
        profile.get("source_file", ""),
        " ".join(sorted(profile.get("issuers") or [])),
        " ".join(sorted(profile.get("project_names") or [])),
        " ".join(sorted(profile.get("aliases") or [])),
        " ".join(profile.get("summary_texts") or []),
    ]
    return " ".join(str(value) for value in values if value)


def score_doc_profile(question: str, profile: dict[str, Any], existing_rank: int | None) -> float:
    q_compact = compact(question)
    text = profile_match_text(profile)
    text_compact = compact(text)
    score = 0.0

    if existing_rank is not None:
        score += max(0.0, 45.0 - existing_rank * 4.0)

    for target in quoted_targets(question):
        target_compact = compact(target)
        if not target_compact:
            continue
        if target_compact in text_compact:
            score += 80.0 + min(len(target_compact), 40)
        elif any(part and part in text_compact for part in re.findall(r"[0-9A-Za-z가-힣]{3,}", target)):
            score += 25.0

    for issuer in profile.get("issuers") or []:
        issuer_compact = compact(issuer)
        if issuer_compact and issuer_compact in q_compact:
            score += 35.0

    for project in profile.get("project_names") or []:
        project_compact = compact(project)
        if project_compact and project_compact in q_compact:
            score += 60.0

    for term in question_terms(question):
        term_compact = compact(term)
        if term_compact and term_compact in text_compact:
            score += min(len(term_compact), 10) * 1.2

    return score


def expanded_doc_keys(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    *,
    max_docs: int,
    existing_boost: bool = True,
) -> list[str]:
    question = str(row.get("question") or row.get("eval_question") or "")
    existing = []
    for idx, key in enumerate(base.context_doc_keys(row), 1):
        primary = alias_to_primary.get(key, key)
        if primary in profiles and primary not in existing:
            existing.append(primary)

    existing_rank = {key: idx for idx, key in enumerate(existing, 1)}
    scored = []
    for key, profile in profiles.items():
        rank = existing_rank.get(key) if existing_boost else None
        score = score_doc_profile(question, profile, rank)
        if score > 0:
            scored.append((score, key))
    scored.sort(key=lambda item: item[0], reverse=True)

    result = []
    for _, key in scored:
        if key not in result:
            result.append(key)
        if len(result) >= max_docs:
            break
    for key in existing:
        if key not in result:
            result.append(key)
        if len(result) >= max_docs:
            break
    return result[:max_docs]


def required_fact_types(intents: set[str]) -> set[str]:
    required: set[str] = set()
    if "budget" in intents:
        required.update({"project_budget", "budget", "estimated_price", "base_amount"})
    if "date" in intents:
        required.update(
            {
                "duration",
                "project_duration",
                "submission_deadline",
                "submission_period",
                "maintenance_period",
                "warranty_period",
                "deadline_term",
                "bid_deadline",
            }
        )
    if "submission" in intents:
        required.update({"submission_documents", "submission_logistics"})
    if "eligibility" in intents:
        required.update({"eligibility", "qualification"})
    if "summary" in intents or "general" in intents:
        required.update({"document_summary", "business_type", "requirements"})
    required.update({"document_summary"})
    return required


def source_final_boost(chunk: dict[str, Any], intents: set[str], source_index: dict[str, dict[str, Any]]) -> float:
    record = source_record_for_chunk(chunk, source_index)
    if not record:
        return 0.0
    score = 0.0
    status = str(record.get("final_budget_status") or "").lower()
    if "budget" in intents and record.get("final_budget_krw"):
        score += 42.0
        if status in {"manual_reviewed", "verified", "g2b_verified", "reviewed"}:
            score += 18.0
        if str(record.get("final_budget_type") or "") in {"project_budget", "total_allocation", "budget"}:
            score += 8.0
    if "date" in intents:
        for key in (
            "final_project_duration",
            "final_maintenance_period",
            "final_warranty_period",
            "final_deadline_terms",
            "final_bid_deadline",
        ):
            if record.get(key):
                score += 14.0
    return score


def score_expanded_chunk(
    chunk: dict[str, Any],
    question: str,
    intents: set[str],
    source_index: dict[str, dict[str, Any]],
    *,
    variant: str,
) -> float:
    score = base.score_chunk(chunk, question, intents, "core_fact_pack_rr")
    fact_type = base.chunk_fact_type(chunk)
    required = required_fact_types(intents)
    if fact_type in required:
        score += 28.0
    score += source_final_boost(chunk, intents, source_index)
    if variant == "expanded_core_required_canonical":
        # Canonical fact order is handled by sorting; keep score useful for diagnostics.
        score += max(0, 20 - base.fact_order_key(chunk)[0])
    return score


def context_from_chunk(
    chunk: dict[str, Any],
    rank: int,
    score: float,
    variant: str,
    source_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context = base.to_context(chunk, rank, score, variant)
    source = source_record_for_chunk(chunk, source_index)
    metadata = dict(context.get("metadata") or {})
    if source:
        for key in SOURCE_FINAL_FIELDS:
            if source.get(key):
                metadata[key] = source.get(key)
        metadata["source_store_id"] = source.get("source_store_id") or metadata.get("source_store_id")
    context["metadata"] = metadata
    context["source_store_id"] = metadata.get("source_store_id", "")
    return context


def existing_doc_keys(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    *,
    max_docs: int,
) -> list[str]:
    result = []
    for key in base.context_doc_keys(row):
        primary = alias_to_primary.get(key, key)
        if primary in profiles and primary not in result:
            result.append(primary)
        if len(result) >= max_docs:
            break
    return result


def select_expanded(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    *,
    variant: str,
    max_docs: int,
    max_per_doc: int,
    total_k: int,
) -> list[dict[str, Any]]:
    question = str(row.get("question") or row.get("eval_question") or "")
    intents = base.classify_question_terms(question)
    if variant.startswith("existing_"):
        doc_keys = existing_doc_keys(row, profiles, alias_to_primary, max_docs=max_docs)
    else:
        doc_keys = expanded_doc_keys(row, profiles, alias_to_primary, max_docs=max_docs)
    required = required_fact_types(intents)
    use_required_first = "required" in variant and "no_required" not in variant
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]] = []
    seen: set[str] = set()

    for doc_key in doc_keys:
        profile = profiles.get(doc_key)
        if not profile:
            continue
        candidates = [chunk for chunk in profile["chunks"] if base.is_fact_candidate(chunk)]
        scored = [
            (score_expanded_chunk(chunk, question, intents, source_index, variant=variant), chunk)
            for chunk in candidates
        ]
        scored = [(score, chunk) for score, chunk in scored if score > 0]

        if "canonical" in variant:
            scored.sort(key=lambda item: (base.fact_order_key(item[1]), -item[0]))
        else:
            scored.sort(key=lambda item: (item[0], str(item[1].get("chunk_id") or "")), reverse=True)

        if use_required_first:
            required_first = []
            rest = []
            for score, chunk in scored:
                if base.chunk_fact_type(chunk) in required:
                    required_first.append((score + 1000.0, chunk))
                else:
                    rest.append((score, chunk))
            ordered = required_first + rest
        else:
            ordered = scored

        picks: list[tuple[float, dict[str, Any]]] = []
        for score, chunk in ordered:
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen:
                continue
            picks.append((score, chunk))
            seen.add(chunk_id)
            if len(picks) >= max_per_doc:
                break
        per_doc_picks.append(picks)

    selected: list[tuple[float, dict[str, Any]]] = []
    if "doc_sequential" in variant:
        for picks in per_doc_picks:
            selected.extend(picks)
            if len(selected) >= total_k:
                break
    else:
        for offset in range(max_per_doc):
            for picks in per_doc_picks:
                if offset < len(picks):
                    selected.append(picks[offset])
                    if len(selected) >= total_k:
                        break
            if len(selected) >= total_k:
                break

    return [
        context_from_chunk(chunk, rank, score, variant, source_index)
        for rank, (score, chunk) in enumerate(selected[:total_k], 1)
    ]


def variant_rows(
    predictions: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    *,
    variant: str,
    max_docs: int,
    max_per_doc: int,
    total_k: int,
) -> list[dict[str, Any]]:
    rows = []
    for row in predictions:
        selected = select_expanded(
            row,
            profiles,
            alias_to_primary,
            source_index,
            variant=variant,
            max_docs=max_docs,
            max_per_doc=max_per_doc,
            total_k=total_k,
        )
        new_row = dict(row)
        new_row["retrieved_contexts_original_count"] = len(row.get("retrieved_contexts") or [])
        new_row["retrieved_contexts"] = selected
        new_row["retrieved_docs"] = base.unique_keep_order(
            [str(item.get("source_file") or item.get("filename") or "") for item in selected]
        )
        new_row["evidence_blocks"] = [
            {
                "source_file": item.get("source_file"),
                "chunk_id": item.get("chunk_id"),
                "rank": item.get("rank"),
                "score": item.get("score"),
                "chunk_type": item.get("metadata", {}).get("chunk_type"),
                "fact_type": item.get("metadata", {}).get("fact_type"),
                "text": item.get("text"),
                "selection_stage": variant,
            }
            for item in selected
        ]
        new_row["evidence_selection_variant"] = variant
        new_row["evidence_selection_config"] = {
            "max_docs": max_docs,
            "max_per_doc": max_per_doc,
            "total_k": total_k,
            "candidate_doc_expansion": True,
            "source_store_final_field_boost": True,
            "required_fact_type_quota": True,
        }
        rows.append(new_row)
    return rows


def flatten_summary(variant: str, summary: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    row = {"variant": variant, **config}
    for key, value in summary.items():
        if key == "diagnosis_counts":
            for diag_key, diag_count in value.items():
                row[diag_key] = diag_count
        elif isinstance(value, float):
            row[key] = round(value, 6)
        else:
            row[key] = value
    return row


def write_summary_md(path: Path, comparison_rows: list[dict[str, Any]], output_dir: Path) -> None:
    lines = [
        "# Expanded Evidence Selection Experiment",
        "",
        "candidate docs 확장, 문서별 required fact_type 보장, source_store final_* 필드 보정을 조합한 참고용 실험입니다.",
        "",
        f"- output_dir: `{output_dir}`",
        "",
        "| rank | variant | evidence_recall@5 | evidence_hit@5 | context_evidence_recall | doc_recall@5 | doc_hit_but_evidence_missed | max_docs | max_per_doc | total_k |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(comparison_rows, 1):
        lines.append(
            f"| {idx} | {row['variant']} | {float(row.get('evidence_recall_at_5', 0)):.4f} | "
            f"{float(row.get('evidence_hit_at_5', 0)):.4f} | {float(row.get('context_evidence_recall', 0)):.4f} | "
            f"{float(row.get('doc_recall_at_5', 0)):.4f} | {row.get('doc_hit_but_evidence_missed', 0)} | "
            f"{row.get('max_docs', '')} | {row.get('max_per_doc', '')} | {row.get('total_k', '')} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- gold evidence는 선택에 사용하지 않고, 마지막 평가에만 사용했습니다.",
            "- candidate docs는 질문 텍스트와 source_file/issuer/project_name/document_summary의 lexical match로 확장했습니다.",
            "- 이 결과는 generation 점수가 아니라, generation context에 정답 evidence가 들어갈 가능성을 보는 진단 점수입니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=base.DEFAULT_PREDICTIONS)
    parser.add_argument("--chunks", type=Path, default=base.DEFAULT_CHUNKS)
    parser.add_argument("--source-store", type=Path, default=DEFAULT_SOURCE_STORE)
    parser.add_argument("--gold", type=Path, default=base.DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", default="5,10,20")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k_values = [int(value.strip()) for value in args.top_k.split(",") if value.strip()]
    output_dir = args.output_dir / args.predictions.stem
    variants_dir = output_dir / "variant_predictions"
    diagnostics_dir = output_dir / "diagnostics"
    variants_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    predictions = base.read_jsonl(args.predictions)
    gold_rows = base.read_jsonl(args.gold)
    chunks = base.load_chunks(args.chunks)
    profiles, alias_to_primary = load_doc_profiles(chunks)
    source_index = load_source_store(args.source_store)

    comparison_rows: list[dict[str, Any]] = []
    baseline = base.score_prediction_rows(predictions, gold_rows, top_k_values)
    comparison_rows.append(flatten_summary("baseline_existing_context", baseline, {}))

    settings = [
        ("existing_core_rr_source_final", 5, 8, 30),
        ("existing_canonical_source_final", 5, 8, 30),
        ("existing_doc_sequential_canonical", 5, 8, 30),
        ("expanded_doc_sequential_canonical_docs6", 6, 8, 30),
        ("expanded_canonical_no_required_docs6", 6, 8, 30),
        ("expanded_canonical_no_required_docs10", 10, 8, 40),
        ("expanded_core_required_docs6", 6, 8, 30),
        ("expanded_core_required_docs10", 10, 8, 40),
        ("expanded_core_required_docs15", 15, 8, 50),
        ("expanded_core_required_canonical", 10, 8, 40),
    ]

    for variant, max_docs, max_per_doc, total_k in settings:
        rows = variant_rows(
            predictions,
            profiles,
            alias_to_primary,
            source_index,
            variant=variant,
            max_docs=max_docs,
            max_per_doc=max_per_doc,
            total_k=total_k,
        )
        variant_path = variants_dir / f"{variant}.jsonl"
        base.write_jsonl(variant_path, rows)
        summary = base.score_prediction_rows(rows, gold_rows, top_k_values)
        comparison_rows.append(
            flatten_summary(
                variant,
                summary,
                {"max_docs": max_docs, "max_per_doc": max_per_doc, "total_k": total_k},
            )
        )

        predictions_by_id = {str(row.get("id") or ""): row for row in rows}
        diag_rows = [
            recall_diag.make_row(
                gold_row,
                predictions_by_id.get(str(gold_row.get("id") or "")),
                top_k_values,
            )
            for gold_row in gold_rows
        ]
        diag_dir = diagnostics_dir / variant
        diag_dir.mkdir(parents=True, exist_ok=True)
        recall_diag.write_csv(diag_dir / "evidence_recall_results.csv", diag_rows)
        recall_diag.write_csv(
            diag_dir / "evidence_recall_failures.csv",
            [
                row
                for row in diag_rows
                if row["diagnosis"]
                in {"doc_hit_but_evidence_missed", "evidence_missed", "evidence_partially_retrieved"}
            ],
        )
        recall_diag.write_summary_md(
            diag_dir / "evidence_recall_summary.md",
            summary,
            diag_rows,
            variant_path,
            args.gold,
            top_k_values,
            20,
        )

    comparison_rows.sort(
        key=lambda row: (
            float(row.get("evidence_recall_at_5") or 0),
            float(row.get("evidence_hit_at_5") or 0),
            float(row.get("context_evidence_recall") or 0),
        ),
        reverse=True,
    )
    base.write_csv(output_dir / "comparison.csv", comparison_rows)
    write_summary_md(output_dir / "summary.md", comparison_rows, output_dir)
    print(json.dumps(comparison_rows, ensure_ascii=False, indent=2))
    print(f"\nWrote expanded evidence selection experiment to {output_dir}")


if __name__ == "__main__":
    main()
