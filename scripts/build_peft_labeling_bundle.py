#!/usr/bin/env python3
"""Build a compact question/context bundle for external answer labeling.

The output is meant to be sent to a stronger LLM or human reviewer to create
PEFT/SFT target answers. It intentionally omits previous generated answers so
the labeler is guided by evidence, not by an older model's mistakes.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_GOLD_PATH = Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl")
DEFAULT_PREDICTIONS_PATH = Path(
    "outputs/generation/final_690_phase34_gold_qwen/"
    "126_service_route_v3_nonbudget_patch_123_budget_50_eval_predictions.jsonl"
)
DEFAULT_SOURCE_STORE_PATH = Path("data/processed/source_store_v2_690.jsonl")
DEFAULT_OUTPUT_PATH = Path("outputs/peft/question_context_bundle_for_labeling.jsonl")
DEFAULT_PROMPT_PATH = Path("outputs/peft/chatgpt_labeling_prompt.md")
DEFAULT_MANIFEST_PATH = Path("outputs/peft/question_context_bundle_manifest.json")


SOURCE_CORE_FIELDS = {
    "source_store_id",
    "doc_id",
    "canonical_doc_id",
    "doc_key",
    "canonical_doc_key",
    "source_file",
    "source_file_nfc",
    "issuer",
    "project_name",
    "final_notice_id",
    "g2b_notice_id",
    "g2b_title",
    "g2b_notice_agency",
    "g2b_demand_agency",
    "section_path",
    "section_type",
    "chunk_type",
    "source_type",
    "budget_value_role",
    "budget_policy_note",
    "answer_policy",
    "answer_risk_level",
    "budget_answer_enabled",
    "eligibility_answer_enabled",
    "payment_answer_enabled",
}


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


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[\s_\-()[\]{}'\".,/\\:;|]+", "", text)
    return text


def truncate(value: Any, max_chars: int) -> str:
    text = normalize_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + " ...[truncated]"


def question_id(row: dict[str, Any]) -> str:
    return str(row.get("question_id") or row.get("id") or "").strip()


def task_family_from_gold(gold: dict[str, Any]) -> str:
    task = gold.get("task_family") or gold.get("question_type") or ""
    return str(task)


def gold_reference(gold: dict[str, Any]) -> dict[str, Any]:
    """Keep structured gold hints for labeling, not the previous model answer."""
    keys = [
        "task_family",
        "secondary_task_families",
        "question_type",
        "difficulty",
        "source_docs",
        "identity_gold",
        "evidence_refs",
        "budget_gold",
        "required_fields_gold",
        "submission_eligibility_deadline_gold",
        "multi_doc_comparison_gold",
        "unanswerable_gold",
        "notes",
    ]
    return {key: gold[key] for key in keys if key in gold and gold[key] not in (None, "", [], {})}


def compact_context(ctx: dict[str, Any], text_max_chars: int) -> dict[str, Any]:
    metadata = ctx.get("metadata") or {}
    source_store_id = ctx.get("source_store_id") or metadata.get("source_store_id") or ""
    return {
        "rank": ctx.get("rank"),
        "score": ctx.get("score"),
        "doc_id": ctx.get("doc_id") or metadata.get("doc_id") or "",
        "source_file": normalize_text(
            ctx.get("source_file") or ctx.get("filename") or metadata.get("source_file") or ""
        ),
        "chunk_id": ctx.get("chunk_id") or metadata.get("chunk_id") or "",
        "source_store_id": source_store_id,
        "chunk_type": metadata.get("chunk_type") or ctx.get("chunk_type") or "",
        "fact_type": metadata.get("fact_type") or ctx.get("fact_type") or "",
        "section_path": metadata.get("section_path") or ctx.get("section_path") or "",
        "issuer": metadata.get("issuer") or "",
        "project_name": metadata.get("project_name") or "",
        "budget": metadata.get("budget") or "",
        "text": truncate(ctx.get("text") or "", text_max_chars),
    }


def source_store_key_set_from_prediction(pred: dict[str, Any], gold: dict[str, Any]) -> dict[str, set[str]]:
    ids: set[str] = set()
    doc_ids: set[str] = set()
    files: set[str] = set()
    normalized_files: set[str] = set()

    for ctx in pred.get("retrieved_contexts") or []:
        metadata = ctx.get("metadata") or {}
        source_store_id = ctx.get("source_store_id") or metadata.get("source_store_id")
        if source_store_id:
            ids.add(str(source_store_id))
        doc_id = ctx.get("doc_id") or metadata.get("doc_id")
        if doc_id:
            doc_ids.add(str(doc_id))
        source_file = ctx.get("source_file") or ctx.get("filename") or metadata.get("source_file")
        if source_file:
            files.add(normalize_text(source_file))
            normalized_files.add(normalize_key(source_file))

    for source_file in gold.get("source_docs") or []:
        files.add(normalize_text(source_file))
        normalized_files.add(normalize_key(source_file))

    for ref in gold.get("evidence_refs") or []:
        if isinstance(ref, dict):
            if ref.get("source_file"):
                files.add(normalize_text(ref["source_file"]))
                normalized_files.add(normalize_key(ref["source_file"]))
            if ref.get("chunk_id"):
                ids.add(str(ref["chunk_id"]))

    return {
        "source_store_ids": ids,
        "doc_ids": doc_ids,
        "source_files": files,
        "normalized_source_files": normalized_files,
    }


def should_keep_source_store(row: dict[str, Any], targets: dict[str, set[str]]) -> bool:
    source_store_id = str(row.get("source_store_id") or "")
    if source_store_id and source_store_id in targets["source_store_ids"]:
        return True
    doc_id = str(row.get("doc_id") or "")
    canonical_doc_id = str(row.get("canonical_doc_id") or "")
    if doc_id in targets["doc_ids"] or canonical_doc_id in targets["doc_ids"]:
        return True
    file_values = [
        row.get("source_file"),
        row.get("source_file_nfc"),
        row.get("doc_key"),
        row.get("canonical_doc_key"),
    ]
    normalized = {normalize_key(v) for v in file_values if v}
    return bool(normalized & targets["normalized_source_files"])


def compact_source_store(row: dict[str, Any], source_text_max_chars: int) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in row.items():
        if value in (None, "", [], {}):
            continue
        include = (
            key in SOURCE_CORE_FIELDS
            or key.startswith("final_")
            or key.endswith("_status")
            or "deadline" in key
            or "duration" in key
            or "budget" in key
            or "eligibility" in key
            or "payment" in key
        )
        if not include:
            continue
        if key == "full_text":
            compact[key] = truncate(value, source_text_max_chars)
        else:
            compact[key] = truncate(value, 500) if isinstance(value, str) else value
    if "full_text" not in compact and row.get("full_text"):
        compact["full_text"] = truncate(row["full_text"], source_text_max_chars)
    return compact


def load_matched_source_store(
    source_store_path: Path,
    targets_by_qid: dict[str, dict[str, set[str]]],
    source_text_max_chars: int,
    max_source_items: int,
) -> dict[str, list[dict[str, Any]]]:
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with source_store_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            for qid, targets in targets_by_qid.items():
                if len(matches[qid]) >= max_source_items:
                    continue
                if should_keep_source_store(row, targets):
                    compact = compact_source_store(row, source_text_max_chars)
                    if compact:
                        matches[qid].append(compact)
    return dict(matches)


def build_prompt_text() -> str:
    return """# ChatGPT labeling prompt

너는 RFP 문서 기반 QA 학습 데이터를 만드는 검수 보조자다.

내가 제공하는 데이터에는 question, retrieved_contexts, source_store, gold_reference가 들어 있다.
너의 목표는 PEFT/SFT 학습에 사용할 수 있는 고품질 정답 답변을 만드는 것이다.

중요 규칙:
1. 반드시 제공된 retrieved_contexts와 source_store 안의 정보만 사용한다.
2. 문서에 없는 내용은 추측하지 않는다.
3. 답을 알 수 없으면 "문서에서 확인할 수 없습니다"라고 답한다.
4. 금액, 날짜, 기간, 공고번호, 기관명, 사업명은 원문 표현을 우선 보존한다.
5. 금액이 "천원" 단위로 되어 있으면 원문 금액과 원 단위 환산값을 함께 적는다.
   예: 원문: 1,515,000천원 / 환산: 1,515,000,000원
6. 여러 문서를 비교하는 질문이면 문서별로 나눠서 답변한다.
7. 답변에는 반드시 근거 문서명과 근거 문장을 포함한다.
8. retrieved_contexts와 source_store가 서로 충돌하면 확정하지 말고 충돌 사실을 표시한다.
9. PEFT 학습에 바로 넣기 어려운 경우 needs_human_review=true로 표시한다.
10. gold_reference는 평가자가 만든 참고 정답 구조다. 단, 실제 답변은 retrieved_contexts/source_store 근거와 충돌하지 않는 범위에서 작성한다.

출력은 반드시 JSONL 형식으로 작성한다.
각 줄은 하나의 JSON 객체여야 한다.

출력 필드:
- question_id
- question
- answer
- evidence_documents
- evidence_sentences
- normalized_values
- confidence: high | medium | low
- needs_human_review: true | false
- review_reason
- trainable: true | false

answer 작성 형식:
- 간결하지만 문서 기반으로 충분히 설명한다.
- 숫자/날짜/기간은 근거 문장과 함께 제시한다.
- 불확실한 경우 단정하지 않는다.

이제 question_context_bundle_for_labeling.jsonl 데이터를 보고 각 question_id별 정답 답변을 만들어라.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-path", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS_PATH)
    parser.add_argument("--source-store-path", type=Path, default=DEFAULT_SOURCE_STORE_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--max-retrieved-contexts", type=int, default=10)
    parser.add_argument("--context-text-max-chars", type=int, default=1400)
    parser.add_argument("--max-source-items", type=int, default=6)
    parser.add_argument("--source-text-max-chars", type=int, default=1200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gold_rows = load_jsonl(args.gold_path)
    pred_rows = load_jsonl(args.predictions_path)
    gold_by_qid = {question_id(row): row for row in gold_rows}
    pred_by_qid = {question_id(row): row for row in pred_rows}

    missing_predictions = sorted(set(gold_by_qid) - set(pred_by_qid))
    if missing_predictions:
        raise SystemExit(f"Missing predictions for {len(missing_predictions)} questions: {missing_predictions[:10]}")

    targets_by_qid = {
        qid: source_store_key_set_from_prediction(pred_by_qid[qid], gold)
        for qid, gold in gold_by_qid.items()
    }
    source_store_by_qid = load_matched_source_store(
        args.source_store_path,
        targets_by_qid,
        source_text_max_chars=args.source_text_max_chars,
        max_source_items=args.max_source_items,
    )

    bundle_rows: list[dict[str, Any]] = []
    for qid in sorted(gold_by_qid):
        gold = gold_by_qid[qid]
        pred = pred_by_qid[qid]
        contexts = [
            compact_context(ctx, args.context_text_max_chars)
            for ctx in (pred.get("retrieved_contexts") or [])[: args.max_retrieved_contexts]
        ]
        bundle_rows.append(
            {
                "question_id": qid,
                "question": gold.get("question") or pred.get("question") or "",
                "task_family": task_family_from_gold(gold),
                "question_type": gold.get("question_type") or "",
                "difficulty": gold.get("difficulty") or "",
                "source_docs": gold.get("source_docs") or [],
                "gold_reference": gold_reference(gold),
                "retrieved_docs_top5": [
                    ctx.get("source_file") or ctx.get("filename") or (ctx.get("metadata") or {}).get("source_file")
                    for ctx in (pred.get("retrieved_contexts") or [])[:5]
                ],
                "retrieved_contexts": contexts,
                "source_store": source_store_by_qid.get(qid, []),
                "labeling_instruction": (
                    "이 항목의 answer를 작성하되, 제공된 retrieved_contexts/source_store 안의 근거만 사용하세요. "
                    "근거가 충돌하거나 부족하면 needs_human_review=true로 표시하세요."
                ),
            }
        )

    write_jsonl(args.output_path, bundle_rows)
    args.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    args.prompt_path.write_text(build_prompt_text(), encoding="utf-8")

    manifest = {
        "bundle_path": str(args.output_path),
        "prompt_path": str(args.prompt_path),
        "gold_path": str(args.gold_path),
        "predictions_path": str(args.predictions_path),
        "source_store_path": str(args.source_store_path),
        "question_count": len(bundle_rows),
        "missing_predictions": missing_predictions,
        "max_retrieved_contexts": args.max_retrieved_contexts,
        "context_text_max_chars": args.context_text_max_chars,
        "max_source_items": args.max_source_items,
        "source_text_max_chars": args.source_text_max_chars,
        "questions_without_source_store": [
            row["question_id"] for row in bundle_rows if not row.get("source_store")
        ],
    }
    args.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] wrote {len(bundle_rows)} rows to {args.output_path}")
    print(f"[OK] wrote prompt to {args.prompt_path}")
    print(f"[OK] wrote manifest to {args.manifest_path}")
    if manifest["questions_without_source_store"]:
        print(f"[WARN] questions without source_store match: {manifest['questions_without_source_store']}")


if __name__ == "__main__":
    main()
