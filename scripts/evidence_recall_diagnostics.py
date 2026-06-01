from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_GOLD_PATH = Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl")
DEFAULT_PREDICTIONS_PATH = Path(
    "outputs/generation/context_mode_compare_phase34_gold_qwen/"
    "rfp_target_evidence_source_store_qwen3_8b_4bit_run1_postprocessed_eval_predictions.jsonl"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_gold_evidence_refs(gold_row: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for ref in gold_row.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        chunk_id = normalize_text(ref.get("chunk_id"))
        if not chunk_id:
            continue
        refs.append(
            {
                "chunk_id": chunk_id,
                "source_file": normalize_text(ref.get("source_file")),
                "fact_type": normalize_text(ref.get("fact_type")),
                "evidence_summary": normalize_text(ref.get("evidence_summary")),
            }
        )
    return refs


def extract_gold_docs(gold_row: dict[str, Any]) -> list[str]:
    docs = [normalize_text(v) for v in gold_row.get("source_docs") or []]
    return unique_keep_order(docs)


def extract_predicted_contexts(pred_row: dict[str, Any]) -> list[dict[str, str]]:
    contexts: list[dict[str, str]] = []
    for idx, item in enumerate(pred_row.get("retrieved_contexts") or []):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        chunk_id = normalize_text(item.get("chunk_id") or metadata.get("chunk_id"))
        source_file = normalize_text(
            item.get("source_file")
            or item.get("filename")
            or metadata.get("source_file")
            or metadata.get("filename")
        )
        contexts.append(
            {
                "rank": str(item.get("rank") or idx + 1),
                "chunk_id": chunk_id,
                "source_file": source_file,
                "fact_type": normalize_text(item.get("fact_type") or metadata.get("fact_type")),
                "chunk_type": normalize_text(item.get("chunk_type") or metadata.get("chunk_type")),
            }
        )
    return contexts


def extract_context_evidence(pred_row: dict[str, Any]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []

    for idx, item in enumerate(pred_row.get("evidence_blocks") or []):
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "rank": str(item.get("rank") or idx + 1),
                "chunk_id": normalize_text(item.get("chunk_id")),
                "source_file": normalize_text(item.get("source_file") or item.get("filename")),
                "fact_type": normalize_text(item.get("fact_type")),
                "chunk_type": normalize_text(item.get("chunk_type")),
            }
        )

    for idx, item in enumerate(pred_row.get("evidence_sentences") or []):
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "rank": str(item.get("rank") or idx + 1),
                "chunk_id": normalize_text(item.get("chunk_id")),
                "source_file": normalize_text(item.get("source_file") or item.get("filename")),
                "fact_type": normalize_text(item.get("fact_type")),
                "chunk_type": normalize_text(item.get("chunk_type")),
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.get("chunk_id", ""), item.get("source_file", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def score_recall(gold_ids: set[str], predicted_ids: list[str]) -> tuple[int, float, list[str], list[str]]:
    if not gold_ids:
        return 0, 0.0, [], []
    predicted_set = {value for value in predicted_ids if value}
    matched = sorted(gold_ids & predicted_set)
    missing = sorted(gold_ids - predicted_set)
    hit = int(bool(matched))
    recall = len(matched) / len(gold_ids)
    return hit, recall, matched, missing


def score_doc_recall(gold_docs: set[str], predicted_docs: list[str]) -> tuple[int, float, list[str], list[str]]:
    if not gold_docs:
        return 0, 0.0, [], []
    predicted_set = {value for value in predicted_docs if value}
    matched = sorted(gold_docs & predicted_set)
    missing = sorted(gold_docs - predicted_set)
    return int(bool(matched)), len(matched) / len(gold_docs), matched, missing


def make_row(
    gold_row: dict[str, Any],
    pred_row: dict[str, Any] | None,
    top_k_values: list[int],
) -> dict[str, Any]:
    gold_refs = extract_gold_evidence_refs(gold_row)
    gold_chunk_ids = {ref["chunk_id"] for ref in gold_refs if ref["chunk_id"]}
    gold_docs = set(extract_gold_docs(gold_row))
    pred_row = pred_row or {}
    retrieved_contexts = extract_predicted_contexts(pred_row)
    context_evidence = extract_context_evidence(pred_row)

    row: dict[str, Any] = {
        "id": gold_row.get("id"),
        "question": gold_row.get("question"),
        "task_family": gold_row.get("task_family"),
        "question_type": gold_row.get("question_type"),
        "difficulty": gold_row.get("difficulty"),
        "prediction_missing": not bool(pred_row),
        "gold_doc_count": len(gold_docs),
        "gold_evidence_count": len(gold_chunk_ids),
        "retrieved_context_count": len(retrieved_contexts),
        "context_evidence_count": len(context_evidence),
        "gold_docs": json.dumps(sorted(gold_docs), ensure_ascii=False),
        "gold_chunk_ids": json.dumps(sorted(gold_chunk_ids), ensure_ascii=False),
    }

    for top_k in top_k_values:
        top_contexts = retrieved_contexts[:top_k]
        predicted_chunk_ids = [item["chunk_id"] for item in top_contexts]
        predicted_docs = [item["source_file"] for item in top_contexts]
        e_hit, e_recall, e_matched, e_missing = score_recall(gold_chunk_ids, predicted_chunk_ids)
        d_hit, d_recall, d_matched, d_missing = score_doc_recall(gold_docs, predicted_docs)
        row[f"evidence_hit_at_{top_k}"] = e_hit
        row[f"evidence_recall_at_{top_k}"] = round(e_recall, 6)
        row[f"matched_gold_chunk_ids_at_{top_k}"] = json.dumps(e_matched, ensure_ascii=False)
        row[f"missing_gold_chunk_ids_at_{top_k}"] = json.dumps(e_missing, ensure_ascii=False)
        row[f"doc_hit_at_{top_k}"] = d_hit
        row[f"doc_recall_at_{top_k}"] = round(d_recall, 6)
        row[f"matched_gold_docs_at_{top_k}"] = json.dumps(d_matched, ensure_ascii=False)
        row[f"missing_gold_docs_at_{top_k}"] = json.dumps(d_missing, ensure_ascii=False)
        row[f"retrieved_docs_at_{top_k}"] = json.dumps(
            unique_keep_order(predicted_docs), ensure_ascii=False
        )
        row[f"retrieved_chunk_ids_at_{top_k}"] = json.dumps(
            unique_keep_order(predicted_chunk_ids), ensure_ascii=False
        )

    context_chunk_ids = [item["chunk_id"] for item in context_evidence]
    c_hit, c_recall, c_matched, c_missing = score_recall(gold_chunk_ids, context_chunk_ids)
    row["context_evidence_hit"] = c_hit
    row["context_evidence_recall"] = round(c_recall, 6)
    row["matched_context_gold_chunk_ids"] = json.dumps(c_matched, ensure_ascii=False)
    row["missing_context_gold_chunk_ids"] = json.dumps(c_missing, ensure_ascii=False)
    row["context_chunk_ids"] = json.dumps(unique_keep_order(context_chunk_ids), ensure_ascii=False)

    if not gold_chunk_ids:
        diagnosis = "no_gold_evidence_labels"
    elif not pred_row:
        diagnosis = "prediction_missing"
    elif row.get("doc_hit_at_5") and not row.get("evidence_hit_at_5"):
        diagnosis = "doc_hit_but_evidence_missed"
    elif row.get("evidence_recall_at_5") == 1:
        diagnosis = "evidence_fully_retrieved"
    elif row.get("evidence_hit_at_5"):
        diagnosis = "evidence_partially_retrieved"
    else:
        diagnosis = "evidence_missed"
    row["diagnosis"] = diagnosis
    return row


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]], top_k_values: list[int]) -> dict[str, Any]:
    scored = [row for row in rows if int(row["gold_evidence_count"]) > 0]
    summary: dict[str, Any] = {
        "num_questions": len(rows),
        "num_scored_questions": len(scored),
        "num_without_gold_evidence_labels": len(rows) - len(scored),
    }
    for top_k in top_k_values:
        summary[f"evidence_hit_at_{top_k}"] = mean(
            float(row[f"evidence_hit_at_{top_k}"]) for row in scored
        ) if scored else 0.0
        summary[f"evidence_recall_at_{top_k}"] = mean(
            float(row[f"evidence_recall_at_{top_k}"]) for row in scored
        ) if scored else 0.0
        summary[f"doc_recall_at_{top_k}"] = mean(
            float(row[f"doc_recall_at_{top_k}"]) for row in scored
        ) if scored else 0.0
    summary["context_evidence_hit"] = mean(
        float(row["context_evidence_hit"]) for row in scored
    ) if scored else 0.0
    summary["context_evidence_recall"] = mean(
        float(row["context_evidence_recall"]) for row in scored
    ) if scored else 0.0
    by_diagnosis: dict[str, int] = defaultdict(int)
    for row in rows:
        by_diagnosis[str(row["diagnosis"])] += 1
    summary["diagnosis_counts"] = dict(sorted(by_diagnosis.items()))
    return summary


def write_summary_md(
    path: Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    predictions_path: Path,
    gold_path: Path,
    top_k_values: list[int],
    max_examples: int,
) -> None:
    lines: list[str] = []
    lines.append("# Evidence Recall Diagnostics")
    lines.append("")
    lines.append("기존 eval 채점 로직과 분리해서, gold `evidence_refs.chunk_id`가 검색 결과나 실제 context에 포함됐는지만 확인한 참고용 리포트입니다.")
    lines.append("")
    lines.append(f"- gold: `{gold_path}`")
    lines.append(f"- predictions: `{predictions_path}`")
    lines.append(f"- num_questions: {summary['num_questions']}")
    lines.append(f"- num_scored_questions: {summary['num_scored_questions']}")
    lines.append(f"- num_without_gold_evidence_labels: {summary['num_without_gold_evidence_labels']}")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---:|")
    for top_k in top_k_values:
        lines.append(f"| evidence_hit_at_{top_k} | {summary[f'evidence_hit_at_{top_k}']:.4f} |")
        lines.append(f"| evidence_recall_at_{top_k} | {summary[f'evidence_recall_at_{top_k}']:.4f} |")
        lines.append(f"| doc_recall_at_{top_k} | {summary[f'doc_recall_at_{top_k}']:.4f} |")
    lines.append(f"| context_evidence_hit | {summary['context_evidence_hit']:.4f} |")
    lines.append(f"| context_evidence_recall | {summary['context_evidence_recall']:.4f} |")
    lines.append("")
    lines.append("## Diagnosis Counts")
    lines.append("")
    for key, value in summary["diagnosis_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Failure Examples")
    lines.append("")
    failures = [
        row
        for row in rows
        if row["diagnosis"] in {"doc_hit_but_evidence_missed", "evidence_missed", "evidence_partially_retrieved"}
    ][:max_examples]
    if not failures:
        lines.append("No evidence recall failures found.")
    for row in failures:
        lines.append(f"### {row['id']} - {row['diagnosis']}")
        lines.append("")
        lines.append(f"- question: {row.get('question')}")
        lines.append(f"- task_family: {row.get('task_family')}")
        lines.append(f"- gold_docs: `{row.get('gold_docs')}`")
        lines.append(f"- retrieved_docs_at_5: `{row.get('retrieved_docs_at_5')}`")
        lines.append(f"- evidence_recall_at_5: {row.get('evidence_recall_at_5')}")
        lines.append(f"- context_evidence_recall: {row.get('context_evidence_recall')}")
        lines.append(f"- missing_gold_chunk_ids_at_5: `{row.get('missing_gold_chunk_ids_at_5')}`")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- 이 리포트는 exact `chunk_id` 매칭 기준입니다.")
    lines.append("- gold `evidence_refs`가 불완전하거나 실제 정답 근거보다 넓게/좁게 달려 있으면 점수도 그 영향을 받습니다.")
    lines.append("- `doc_recall`은 문서가 맞았는지, `evidence_recall`은 그 문서 안의 정답 근거 청크까지 맞았는지를 보는 보조 지표입니다.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute standalone evidence/chunk recall diagnostics without changing eval outputs."
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS_PATH)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--top-k", default="5,10,20")
    parser.add_argument("--max-examples", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k_values = [int(value.strip()) for value in args.top_k.split(",") if value.strip()]
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = Path("outputs/evidence_recall") / args.predictions.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    gold_rows = read_jsonl(args.gold)
    prediction_rows = read_jsonl(args.predictions)
    predictions_by_id = {normalize_text(row.get("id")): row for row in prediction_rows}

    rows = [
        make_row(gold_row, predictions_by_id.get(normalize_text(gold_row.get("id"))), top_k_values)
        for gold_row in gold_rows
    ]
    summary = summarize(rows, top_k_values)
    failure_rows = [
        row
        for row in rows
        if row["diagnosis"] in {"doc_hit_but_evidence_missed", "evidence_missed", "evidence_partially_retrieved"}
    ]

    write_jsonl(output_dir / "evidence_recall_results.jsonl", rows)
    write_csv(output_dir / "evidence_recall_results.csv", rows)
    write_csv(output_dir / "evidence_recall_failures.csv", failure_rows)
    (output_dir / "evidence_recall_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary_md(
        output_dir / "evidence_recall_summary.md",
        summary,
        rows,
        args.predictions,
        args.gold,
        top_k_values,
        args.max_examples,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote evidence recall diagnostics to {output_dir}")


if __name__ == "__main__":
    main()
