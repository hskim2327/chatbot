#!/usr/bin/env python3
"""Convert reviewed/LLM-created answer labels into chat SFT JSONL files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_BUNDLE_PATH = Path("outputs/peft/question_context_bundle_for_labeling.jsonl")
DEFAULT_LABELS_PATH = Path("outputs/peft/answer_labels.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/peft")

SYSTEM_PROMPT = """너는 RFP 문서 기반 QA assistant다.
반드시 제공된 Context 안의 정보만 사용한다.
Context에 없으면 추측하지 말고 "문서에서 확인할 수 없습니다"라고 답한다.
금액, 날짜, 기간, 공고번호는 원문 표현을 우선 보존한다.
여러 문서를 묻는 질문은 문서별로 값을 분리한다.
답변에는 근거 문서명과 근거 문장을 함께 제시한다."""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def compact_text(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + " ...[truncated]"


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def qid(row: dict[str, Any]) -> str:
    return str(row.get("question_id") or row.get("id") or "").strip()


def format_context(bundle: dict[str, Any], max_context_chars: int) -> str:
    parts: list[str] = []
    parts.append("[QUESTION]")
    parts.append(str(bundle.get("question") or ""))
    parts.append("")
    parts.append("[QUESTION_METADATA]")
    parts.append(
        json.dumps(
            {
                "question_id": bundle.get("question_id"),
                "task_family": bundle.get("task_family"),
                "question_type": bundle.get("question_type"),
                "difficulty": bundle.get("difficulty"),
                "source_docs": bundle.get("source_docs") or [],
            },
            ensure_ascii=False,
        )
    )
    parts.append("")
    parts.append("[RETRIEVED_CONTEXTS]")
    for ctx in bundle.get("retrieved_contexts") or []:
        header = {
            "rank": ctx.get("rank"),
            "score": ctx.get("score"),
            "source_file": ctx.get("source_file"),
            "doc_id": ctx.get("doc_id"),
            "chunk_id": ctx.get("chunk_id"),
            "chunk_type": ctx.get("chunk_type"),
            "fact_type": ctx.get("fact_type"),
            "section_path": ctx.get("section_path"),
        }
        parts.append(json.dumps(header, ensure_ascii=False))
        parts.append(compact_text(ctx.get("text"), 1200))
        parts.append("")
    parts.append("[SOURCE_STORE]")
    for src in bundle.get("source_store") or []:
        visible = {
            key: src.get(key)
            for key in [
                "source_store_id",
                "doc_id",
                "source_file_nfc",
                "issuer",
                "project_name",
                "final_notice_id",
                "final_budget",
                "final_budget_krw",
                "final_project_duration",
                "final_bid_deadline",
                "budget_value_role",
                "section_path",
                "chunk_type",
            ]
            if src.get(key) not in (None, "", [], {})
        }
        parts.append(json.dumps(visible, ensure_ascii=False))
        if src.get("full_text"):
            parts.append(compact_text(src.get("full_text"), 900))
        parts.append("")
    parts.append("[ANSWER_RULES]")
    parts.append(
        "제공된 Context 안의 근거만 사용하세요. 문서에 없는 내용은 확인 불가라고 답하세요. "
        "숫자/날짜/기간은 원문 표현과 근거 문장을 함께 제시하세요."
    )
    content = "\n".join(parts)
    return compact_text(content, max_context_chars)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-path", type=Path, default=DEFAULT_BUNDLE_PATH)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--valid-ratio", type=float, default=0.2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle_rows = load_jsonl(args.bundle_path)
    label_rows = load_jsonl(args.labels_path)
    bundle_by_id = {qid(row): row for row in bundle_rows}

    trainable_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    missing_bundle: list[str] = []

    for label in label_rows:
        question_id = qid(label)
        bundle = bundle_by_id.get(question_id)
        if not bundle:
            missing_bundle.append(question_id)
            continue
        is_trainable = boolish(label.get("trainable")) and not boolish(label.get("needs_human_review"))
        answer = compact_text(label.get("answer"), 8000)
        record = {
            "question_id": question_id,
            "task_family": bundle.get("task_family"),
            "confidence": label.get("confidence"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": format_context(bundle, args.max_context_chars)},
                {"role": "assistant", "content": answer},
            ],
            "label_metadata": {
                "evidence_documents": label.get("evidence_documents") or [],
                "evidence_sentences": label.get("evidence_sentences") or [],
                "normalized_values": label.get("normalized_values") or {},
                "needs_human_review": boolish(label.get("needs_human_review")),
                "review_reason": label.get("review_reason") or "",
                "trainable": boolish(label.get("trainable")),
            },
        }
        if is_trainable:
            trainable_rows.append(record)
        else:
            review_rows.append({"question_id": question_id, "label": label, "bundle_summary": {
                "task_family": bundle.get("task_family"),
                "question_type": bundle.get("question_type"),
                "source_docs": bundle.get("source_docs") or [],
                "retrieved_docs_top5": bundle.get("retrieved_docs_top5") or [],
            }})

    trainable_rows.sort(key=lambda row: row["question_id"])
    review_rows.sort(key=lambda row: row["question_id"])

    valid_count = max(1, round(len(trainable_rows) * args.valid_ratio)) if len(trainable_rows) > 1 else 0
    valid_rows = trainable_rows[-valid_count:] if valid_count else []
    train_rows = trainable_rows[:-valid_count] if valid_count else trainable_rows

    all_path = args.output_dir / "sft_all_trainable_messages.jsonl"
    train_path = args.output_dir / "sft_train_messages.jsonl"
    valid_path = args.output_dir / "sft_valid_messages.jsonl"
    review_path = args.output_dir / "label_review_needed.jsonl"
    manifest_path = args.output_dir / "sft_dataset_manifest.json"

    write_jsonl(all_path, trainable_rows)
    write_jsonl(train_path, train_rows)
    write_jsonl(valid_path, valid_rows)
    write_jsonl(review_path, review_rows)

    manifest = {
        "bundle_path": str(args.bundle_path),
        "labels_path": str(args.labels_path),
        "all_trainable_path": str(all_path),
        "train_path": str(train_path),
        "valid_path": str(valid_path),
        "review_needed_path": str(review_path),
        "label_rows": len(label_rows),
        "bundle_rows": len(bundle_rows),
        "trainable_rows": len(trainable_rows),
        "train_rows": len(train_rows),
        "valid_rows": len(valid_rows),
        "review_needed_rows": len(review_rows),
        "missing_bundle": missing_bundle,
        "note": "Only rows with trainable=true and needs_human_review=false are included in SFT trainable files.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] trainable all: {len(trainable_rows)} -> {all_path}")
    print(f"[OK] train split: {len(train_rows)} -> {train_path}")
    print(f"[OK] valid split: {len(valid_rows)} -> {valid_path}")
    print(f"[OK] review needed: {len(review_rows)} -> {review_path}")
    print(f"[OK] manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
