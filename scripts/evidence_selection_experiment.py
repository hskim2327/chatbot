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


DEFAULT_PREDICTIONS = Path(
    "outputs/generation/context_mode_compare_phase34_gold_qwen/"
    "rfp_target_evidence_source_store_qwen3_8b_4bit_run1_postprocessed_eval_predictions.jsonl"
)
DEFAULT_CHUNKS = Path("indexes/chroma_kure_v1_chunks_v2_125/chunks.json")
DEFAULT_GOLD = Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/evidence_recall/evidence_selection_experiment")


BUDGET_TERMS = (
    "project_budget",
    "budget",
    "estimated_price",
    "base_amount",
    "사업예산",
    "사업 예산",
    "사업금액",
    "사업 금액",
    "사업비",
    "총사업비",
    "총 사업비",
    "추정가격",
    "추정 금액",
    "배정예산",
)
DATE_TERMS = (
    "project_duration",
    "duration",
    "deadline",
    "bid_deadline",
    "maintenance_period",
    "warranty_period",
    "사업기간",
    "계약기간",
    "수행기간",
    "제출마감",
    "입찰마감",
    "유지보수",
    "하자",
)
SUBMISSION_TERMS = (
    "submission_documents",
    "submission_logistics",
    "제출서류",
    "제출 서류",
    "구비서류",
    "제안서",
    "서식",
    "제출처",
)
ELIGIBILITY_TERMS = (
    "eligibility",
    "qualification",
    "참가자격",
    "참가 자격",
    "입찰자격",
    "실적",
    "공동수급",
)
SUMMARY_TERMS = (
    "document_summary",
    "business_type",
    "requirements",
    "문서요약",
    "사업개요",
    "요구사항",
    "사업유형",
)
IDENTITY_TERMS = ("document_identity", "문서식별", "기관명", "사업명")

DOC_KEY_PUNCT_RE = re.compile(r"[\s_·\\-\\[\\]\\(\\){}.,/\\\\\"'「」『』:;]+")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_chunks(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        chunks = raw.get("chunks") or []
    else:
        chunks = raw
    if not isinstance(chunks, list):
        raise ValueError(f"Unsupported chunks format: {path}")
    return chunks


def normalize_doc_key(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in (".hwp", ".hwpx", ".pdf", ".docx", ".doc"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
            break
    return DOC_KEY_PUNCT_RE.sub("", text).lower()


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def context_doc_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for context in row.get("retrieved_contexts") or []:
        metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
        for value in (
            context.get("source_file"),
            context.get("filename"),
            context.get("doc_id"),
            metadata.get("source_file"),
            metadata.get("doc_key"),
        ):
            key = normalize_doc_key(value)
            if key:
                keys.append(key)
    for value in row.get("retrieved_docs") or []:
        key = normalize_doc_key(value)
        if key:
            keys.append(key)
    return unique_keep_order(keys)


def chunk_doc_keys(chunk: dict[str, Any]) -> set[str]:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    values = [
        chunk.get("doc_id"),
        chunk.get("source_file"),
        metadata.get("source_file"),
        metadata.get("doc_key"),
        metadata.get("project_name"),
    ]
    return {normalize_doc_key(value) for value in values if normalize_doc_key(value)}


def chunk_source_file(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return str(chunk.get("source_file") or metadata.get("source_file") or "")


def chunk_fact_type(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    section = str(metadata.get("section_path") or chunk.get("section_path") or "")
    if ">" in section:
        tail = section.split(">")[-1].strip()
        if tail:
            return tail
    text = str(chunk.get("text") or "")
    lowered = (section + " " + text[:300]).lower()
    if any(term in lowered for term in ("project_budget", "사업예산", "사업금액", "사업비")):
        return "project_budget"
    if any(term in lowered for term in ("document_summary", "문서요약", "사업개요")):
        return "document_summary"
    if any(term in lowered for term in ("document_identity", "문서식별")):
        return "document_identity"
    if any(term in lowered for term in ("submission_documents", "제출서류", "구비서류")):
        return "submission_documents"
    if any(term in lowered for term in ("eligibility", "참가자격", "입찰자격")):
        return "eligibility"
    if any(term in lowered for term in ("duration", "사업기간", "계약기간", "유지보수")):
        return "duration"
    return ""


def classify_question_terms(question: str) -> set[str]:
    q = str(question or "").lower()
    intents: set[str] = set()
    if any(term.lower() in q for term in BUDGET_TERMS) or re.search(r"\d[\d,]*\s*(?:원|만원|억원|%)", q):
        intents.add("budget")
    if any(term.lower() in q for term in DATE_TERMS):
        intents.add("date")
    if any(term.lower() in q for term in SUBMISSION_TERMS):
        intents.add("submission")
    if any(term.lower() in q for term in ELIGIBILITY_TERMS):
        intents.add("eligibility")
    if any(term.lower() in q for term in SUMMARY_TERMS):
        intents.add("summary")
    if len(re.findall(r"(와|과|및|그리고|,)", q)) or any(term in q for term in ("비교", "차액", "합계", "각각", "두 ")):
        intents.add("multi_doc")
    return intents or {"general"}


def intent_terms(intents: set[str]) -> tuple[str, ...]:
    terms: list[str] = []
    if "budget" in intents:
        terms.extend(BUDGET_TERMS)
    if "date" in intents:
        terms.extend(DATE_TERMS)
    if "submission" in intents:
        terms.extend(SUBMISSION_TERMS)
    if "eligibility" in intents:
        terms.extend(ELIGIBILITY_TERMS)
    if "summary" in intents or "general" in intents:
        terms.extend(SUMMARY_TERMS)
    return tuple(dict.fromkeys(terms))


def is_fact_candidate(chunk: dict[str, Any]) -> bool:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return str(metadata.get("chunk_type") or chunk.get("chunk_type") or "") == "fact_candidates"


def score_chunk(chunk: dict[str, Any], question: str, intents: set[str], variant: str) -> float:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    text = str(chunk.get("text") or "")
    section = str(metadata.get("section_path") or "")
    haystack = " ".join([text, section, str(metadata.get("section_type") or "")]).lower()
    fact_type = chunk_fact_type(chunk)

    score = 0.0
    if is_fact_candidate(chunk):
        score += 20.0
    if fact_type == "document_identity":
        score += 1.0
    if fact_type == "document_summary":
        score += 4.0

    wanted_terms = intent_terms(intents)
    for term in wanted_terms:
        if term and term.lower() in haystack:
            score += 8.0
    if "budget" in intents and fact_type in {"project_budget", "budget", "estimated_price", "base_amount"}:
        score += 30.0
    if "date" in intents and any(term in fact_type for term in ("duration", "deadline", "period", "maintenance", "warranty")):
        score += 24.0
    if "submission" in intents and fact_type in {"submission_documents", "submission_logistics"}:
        score += 24.0
    if "eligibility" in intents and fact_type in {"eligibility", "qualification"}:
        score += 24.0
    if "summary" in intents and fact_type in {"document_summary", "business_type", "requirements"}:
        score += 18.0

    if variant == "core_fact_pack":
        if fact_type in {
            "document_identity",
            "document_summary",
            "project_budget",
            "duration",
            "project_duration",
            "submission_documents",
            "eligibility",
            "business_type",
            "requirements",
        }:
            score += 14.0
    elif variant == "intent_focused":
        if fact_type in {"document_identity", "document_summary"}:
            score += 4.0
    elif variant == "budget_priority":
        if fact_type in {"project_budget", "budget", "estimated_price", "base_amount"}:
            score += 36.0
        if fact_type in {"threshold_budget", "payment_terms"}:
            score -= 25.0
    elif variant in {"core_fact_pack_rr", "intent_focused_rr"}:
        if fact_type in {
            "document_identity",
            "document_summary",
            "project_budget",
            "duration",
            "project_duration",
            "submission_documents",
            "eligibility",
            "business_type",
            "requirements",
        }:
            score += 14.0

    for term in re.findall(r"[0-9A-Za-z가-힣]{2,}", question or "")[:12]:
        if term.lower() in haystack:
            score += 0.5
    return score


def fact_order_key(chunk: dict[str, Any]) -> tuple[int, str]:
    fact_type = chunk_fact_type(chunk)
    priority = {
        "document_identity": 1,
        "document_summary": 2,
        "project_budget": 3,
        "budget": 3,
        "estimated_price": 3,
        "base_amount": 3,
        "duration": 4,
        "project_duration": 4,
        "submission_documents": 5,
        "submission_logistics": 6,
        "eligibility": 7,
        "business_type": 8,
        "requirements": 9,
    }.get(fact_type, 50)
    chunk_id = str(chunk.get("chunk_id") or "")
    match = re.search(r"_fact_(\d+)_", chunk_id)
    fact_number = int(match.group(1)) if match else priority
    return (min(priority, fact_number), chunk_id)


def build_chunk_indexes(chunks: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_doc_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id:
            by_id[chunk_id] = chunk
        for key in chunk_doc_keys(chunk):
            by_doc_key[key].append(chunk)
    return dict(by_doc_key), by_id


def source_file_for_doc_key(doc_key: str, chunks: list[dict[str, Any]]) -> str:
    for chunk in chunks:
        if doc_key in chunk_doc_keys(chunk):
            source = chunk_source_file(chunk)
            if source:
                return source
    return doc_key


def to_context(chunk: dict[str, Any], rank: int, score: float, variant: str) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    metadata["generation_context_source"] = "evidence_selection_experiment"
    metadata["fact_type"] = chunk_fact_type(chunk)
    return {
        "rank": rank,
        "filename": chunk_source_file(chunk),
        "source_file": chunk_source_file(chunk),
        "doc_id": chunk.get("doc_id"),
        "chunk_id": chunk.get("chunk_id"),
        "score": score,
        "text": chunk.get("text") or "",
        "metadata": metadata,
        "selection_stage": variant,
    }


def select_for_variant(
    row: dict[str, Any],
    by_doc_key: dict[str, list[dict[str, Any]]],
    variant: str,
    max_docs: int,
    max_per_doc: int,
    total_k: int,
) -> list[dict[str, Any]]:
    question = str(row.get("question") or row.get("eval_question") or "")
    intents = classify_question_terms(question)
    doc_keys = context_doc_keys(row)[:max_docs]
    selected: list[tuple[float, dict[str, Any]]] = []
    per_doc_selected: list[list[tuple[float, dict[str, Any]]]] = []
    seen_ids: set[str] = set()

    for doc_key in doc_keys:
        candidates = by_doc_key.get(doc_key, [])
        if not candidates:
            continue
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in candidates:
            if not is_fact_candidate(chunk):
                continue
            score = score_chunk(chunk, question, intents, variant)
            if score <= 0:
                continue
            scored.append((score, chunk))
        if variant == "canonical_fact_order":
            scored.sort(key=lambda item: fact_order_key(item[1]))
        else:
            scored.sort(key=lambda item: (item[0], str(item[1].get("chunk_id") or "")), reverse=True)

        picked_for_doc = 0
        doc_picks: list[tuple[float, dict[str, Any]]] = []
        for score, chunk in scored:
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id in seen_ids:
                continue
            doc_picks.append((score, chunk))
            seen_ids.add(chunk_id)
            picked_for_doc += 1
            if picked_for_doc >= max_per_doc:
                break
        per_doc_selected.append(doc_picks)

    if variant in {"core_fact_pack_rr", "intent_focused_rr", "canonical_fact_order"}:
        for offset in range(max_per_doc):
            for doc_picks in per_doc_selected:
                if offset < len(doc_picks):
                    selected.append(doc_picks[offset])
                    if len(selected) >= total_k:
                        break
            if len(selected) >= total_k:
                break
    else:
        for doc_picks in per_doc_selected:
            selected.extend(doc_picks)
        selected.sort(key=lambda item: item[0], reverse=True)
    return [to_context(chunk, rank, score, variant) for rank, (score, chunk) in enumerate(selected[:total_k], 1)]


def make_variant_rows(
    predictions: list[dict[str, Any]],
    by_doc_key: dict[str, list[dict[str, Any]]],
    *,
    variant: str,
    max_docs: int,
    max_per_doc: int,
    total_k: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in predictions:
        selected = select_for_variant(
            row,
            by_doc_key,
            variant,
            max_docs=max_docs,
            max_per_doc=max_per_doc,
            total_k=total_k,
        )
        new_row = dict(row)
        new_row["retrieved_contexts_original_count"] = len(row.get("retrieved_contexts") or [])
        new_row["retrieved_contexts"] = selected
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
        new_row["retrieved_docs"] = unique_keep_order(
            [str(item.get("source_file") or item.get("filename") or "") for item in selected]
        )
        new_row["evidence_selection_variant"] = variant
        new_row["evidence_selection_config"] = {
            "max_docs": max_docs,
            "max_per_doc": max_per_doc,
            "total_k": total_k,
        }
        rows.append(new_row)
    return rows


def score_prediction_rows(
    rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    top_k_values: list[int],
) -> dict[str, Any]:
    predictions_by_id = {str(row.get("id") or ""): row for row in rows}
    scored_rows = [
        recall_diag.make_row(gold_row, predictions_by_id.get(str(gold_row.get("id") or "")), top_k_values)
        for gold_row in gold_rows
    ]
    return recall_diag.summarize(scored_rows, top_k_values)


def write_summary_md(path: Path, comparison_rows: list[dict[str, Any]], output_dir: Path) -> None:
    lines = [
        "# Evidence Selection Experiment",
        "",
        "기존 eval과 분리해서, 검색된 문서 안에서 어떤 evidence chunk를 context로 고를지 비교한 참고용 실험입니다.",
        "",
        f"- output_dir: `{output_dir}`",
        "",
        "## Ranking",
        "",
        "| rank | variant | evidence_recall@5 | evidence_hit@5 | context_evidence_recall | doc_recall@5 | doc_hit_but_evidence_missed |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(comparison_rows, 1):
        lines.append(
            f"| {idx} | {row['variant']} | {float(row['evidence_recall_at_5']):.4f} | "
            f"{float(row['evidence_hit_at_5']):.4f} | {float(row['context_evidence_recall']):.4f} | "
            f"{float(row['doc_recall_at_5']):.4f} | {row.get('doc_hit_but_evidence_missed', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `baseline_existing_context`는 기존 prediction의 `retrieved_contexts/evidence_blocks`를 그대로 평가한 값입니다.",
            "- 나머지 variant는 기존 retrieval로 잡힌 문서 목록을 유지한 뒤, 같은 문서 안에서 `fact_candidates` evidence를 다시 고른 값입니다.",
            "- 이 결과는 generation을 새로 돌린 점수가 아니라, generation 전에 context에 정답 근거 청크가 들어갈 가능성을 보는 진단 지표입니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", default="5,10,20")
    parser.add_argument("--max-docs", type=int, default=5)
    parser.add_argument("--max-per-doc", type=int, default=8)
    parser.add_argument("--total-k", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k_values = [int(value.strip()) for value in args.top_k.split(",") if value.strip()]
    output_dir = args.output_dir / args.predictions.stem
    variants_dir = output_dir / "variant_predictions"
    diagnostics_dir = output_dir / "diagnostics"
    variants_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    predictions = read_jsonl(args.predictions)
    gold_rows = read_jsonl(args.gold)
    chunks = load_chunks(args.chunks)
    by_doc_key, _ = build_chunk_indexes(chunks)

    comparison_rows: list[dict[str, Any]] = []

    baseline_summary = score_prediction_rows(predictions, gold_rows, top_k_values)
    baseline_row = flatten_summary("baseline_existing_context", baseline_summary)
    comparison_rows.append(baseline_row)

    variant_settings = [
        ("intent_focused", args.max_docs, min(args.max_per_doc, 5), min(args.total_k, 20)),
        ("intent_focused_rr", args.max_docs, min(args.max_per_doc, 5), min(args.total_k, 20)),
        ("budget_priority", args.max_docs, args.max_per_doc, args.total_k),
        ("core_fact_pack", args.max_docs, args.max_per_doc, args.total_k),
        ("core_fact_pack_rr", args.max_docs, args.max_per_doc, args.total_k),
        ("canonical_fact_order", args.max_docs, args.max_per_doc, args.total_k),
    ]
    for variant, max_docs, max_per_doc, total_k in variant_settings:
        variant_rows = make_variant_rows(
            predictions,
            by_doc_key,
            variant=variant,
            max_docs=max_docs,
            max_per_doc=max_per_doc,
            total_k=total_k,
        )
        variant_path = variants_dir / f"{variant}.jsonl"
        write_jsonl(variant_path, variant_rows)
        summary = score_prediction_rows(variant_rows, gold_rows, top_k_values)
        comparison_row = flatten_summary(variant, summary)
        comparison_row.update({"max_docs": max_docs, "max_per_doc": max_per_doc, "total_k": total_k})
        comparison_rows.append(comparison_row)

        variant_diag_dir = diagnostics_dir / variant
        variant_diag_dir.mkdir(parents=True, exist_ok=True)
        diag_rows = [
            recall_diag.make_row(
                gold_row,
                {str(row.get("id") or ""): row for row in variant_rows}.get(str(gold_row.get("id") or "")),
                top_k_values,
            )
            for gold_row in gold_rows
        ]
        recall_diag.write_csv(variant_diag_dir / "evidence_recall_results.csv", diag_rows)
        recall_diag.write_csv(
            variant_diag_dir / "evidence_recall_failures.csv",
            [
                row
                for row in diag_rows
                if row["diagnosis"]
                in {"doc_hit_but_evidence_missed", "evidence_missed", "evidence_partially_retrieved"}
            ],
        )
        recall_diag.write_summary_md(
            variant_diag_dir / "evidence_recall_summary.md",
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
            float(row.get("context_evidence_recall") or 0),
            float(row.get("evidence_hit_at_5") or 0),
        ),
        reverse=True,
    )
    write_csv(output_dir / "comparison.csv", comparison_rows)
    write_summary_md(output_dir / "summary.md", comparison_rows, output_dir)
    print(json.dumps(comparison_rows, ensure_ascii=False, indent=2))
    print(f"\nWrote evidence selection experiment to {output_dir}")


def flatten_summary(variant: str, summary: dict[str, Any]) -> dict[str, Any]:
    row = {"variant": variant}
    for key, value in summary.items():
        if key == "diagnosis_counts":
            for diag_key, diag_count in value.items():
                row[diag_key] = diag_count
        elif isinstance(value, float):
            row[key] = round(value, 6)
        else:
            row[key] = value
    return row


if __name__ == "__main__":
    main()
