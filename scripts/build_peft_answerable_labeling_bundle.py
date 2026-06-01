#!/usr/bin/env python3
"""Build an answerable-focused PEFT labeling bundle for GPT handoff.

This script intentionally differs from build_peft_extra_labeling_bundle.py:
it avoids D/E guard-heavy rows and selects rows where answer evidence is likely
available in retrieved contexts/source_store. The output is for creating
positive, grounded SFT labels rather than more refusal-heavy labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PREDICTIONS = Path(
    "outputs/predictions/"
    "96_dense_qdecomp_rrf_per75_docscore_mean3_targetaware30_max5_preserve3_relaxed_filter_kure_chroma_690_canonical.jsonl"
)
DEFAULT_SOURCE_STORE = Path("data/processed/source_store_v2_690.jsonl")
DEFAULT_EVAL_DIR = Path("data/eval")
DEFAULT_OUTPUT = Path("outputs/peft/gpt_handoff/question_context_bundle_for_labeling_answerable_v5_50.jsonl")
DEFAULT_MANIFEST = Path("outputs/peft/gpt_handoff/question_context_bundle_for_labeling_answerable_v5_50_manifest.json")
DEFAULT_PROMPT = Path("outputs/peft/gpt_handoff/label_expansion_prompt_answerable_v5.md")
DEFAULT_README = Path("outputs/peft/gpt_handoff/README_answerable_v5.md")

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

CATEGORY_QUOTAS = {
    "budget": 18,
    "required_fields": 14,
    "multi_doc": 12,
    "summary_or_general": 6,
}

BUDGET_QUESTION_RE = re.compile(
    r"예산|금액|합계|차액|얼마|더하면|비율|작은|큰|총액|사업비|기초금액|추정가격|"
    r"\d[\d,]*(?:\.\d+)?\s*(?:원|천원|억원|억)"
)
BUDGET_EVIDENCE_RE = re.compile(
    r"예산|사업비|금액|기초금액|추정가격|배정|편성|"
    r"\d[\d,]*(?:\.\d+)?\s*(?:원|천원|억원|억)"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: Any) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"[\s_\-()[\]{}'\".,/\\:;|·]+", "", text)


def truncate(value: Any, max_chars: int) -> str:
    text = normalize_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + " ...[truncated]"


def question_id(row: dict[str, Any]) -> str:
    return str(row.get("question_id") or row.get("id") or "").strip()


def load_eval_rows(eval_dir: Path, canonical_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, canonical_count + 1):
        path = eval_dir / f"eval_batch_{index:02d}.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                row["source_eval_file"] = path.name
                rows.append(row)
    return rows


def parse_doc_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = []
    return [normalize_text(item) for item in parsed] if isinstance(parsed, list) else []


def parse_structured(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def load_used_ids(paths: list[Path]) -> set[str]:
    used: set[str] = set()
    for path in paths:
        for row in read_jsonl(path):
            qid = question_id(row)
            if qid:
                used.add(qid)
    return used


def category_for(row: dict[str, Any]) -> str:
    question = normalize_text(row.get("question"))
    qtype = normalize_text(row.get("type")).upper()
    if BUDGET_QUESTION_RE.search(question):
        return "budget"
    if re.search(
        r"제출서류|참가자격|자격요건|평가항목|평가기준|입찰마감|마감일|도입|내역|나열|모두|필수|원본|라이선스|수량|서류|조건|기준",
        question,
    ):
        return "required_fields"
    if qtype == "B" or len(parse_doc_list(row.get("ground_truth_docs"))) > 1:
        return "multi_doc"
    return "summary_or_general"


def context_doc_keys(pred: dict[str, Any], max_contexts: int) -> list[str]:
    docs: list[str] = []
    for ctx in (pred.get("retrieved_contexts") or [])[:max_contexts]:
        metadata = ctx.get("metadata") or {}
        source_file = ctx.get("source_file") or ctx.get("filename") or metadata.get("source_file")
        docs.append(normalize_key(source_file))
    return docs


def doc_hit_stats(row: dict[str, Any], pred: dict[str, Any], max_contexts: int) -> dict[str, Any]:
    gold_docs = parse_doc_list(row.get("ground_truth_docs"))
    gold_keys = [normalize_key(doc) for doc in gold_docs]
    retrieved_keys = context_doc_keys(pred, max_contexts)
    matched = [
        doc
        for doc, key in zip(gold_docs, gold_keys)
        if key and any(key in retrieved or retrieved in key for retrieved in retrieved_keys)
    ]
    return {
        "gold_doc_count": len(gold_docs),
        "matched_doc_count": len(matched),
        "matched_docs": matched,
        "all_gold_docs_hit": bool(gold_docs) and len(matched) == len(gold_docs),
        "any_gold_doc_hit": bool(matched),
    }


def evidence_signal(row: dict[str, Any], pred: dict[str, Any], max_contexts: int) -> dict[str, Any]:
    category = category_for(row)
    question = normalize_text(row.get("question"))
    contexts = pred.get("retrieved_contexts") or []
    hay_parts = [question]
    for ctx in contexts[:max_contexts]:
        metadata = ctx.get("metadata") or {}
        hay_parts.extend(
            [
                ctx.get("text") or "",
                metadata.get("fact_type") or "",
                metadata.get("chunk_type") or "",
                metadata.get("section_path") or "",
                metadata.get("budget") or "",
            ]
        )
    hay = normalize_text(" ".join(str(part) for part in hay_parts))
    patterns = {
        "budget": BUDGET_EVIDENCE_RE,
        "required_fields": r"제출서류|참가자격|자격요건|평가항목|평가기준|필수|서류|라이선스|내역|수량|조건|기준",
        "multi_doc": r"사업명|발주기관|목적|범위|예산|기간|제출|자격|구축|개선|비교",
        "summary_or_general": r"목적|배경|범위|기능|구축|개선|시스템|사업|과업|요구사항",
    }
    pattern = patterns.get(category, patterns["summary_or_general"])
    hits = pattern.findall(hay) if hasattr(pattern, "findall") else re.findall(pattern, hay)
    return {
        "category": category,
        "signal_count": len(hits),
        "has_signal": len(hits) >= (2 if category in {"budget", "required_fields"} else 1),
    }


def candidate_score(row: dict[str, Any], pred: dict[str, Any], max_contexts: int) -> tuple[int, str]:
    category = category_for(row)
    doc_stats = doc_hit_stats(row, pred, max_contexts)
    signal = evidence_signal(row, pred, max_contexts)
    score = 0
    reasons: list[str] = []
    if doc_stats["all_gold_docs_hit"]:
        score += 30
        reasons.append("all_gold_docs_in_retrieved_context")
    elif doc_stats["any_gold_doc_hit"]:
        score += 8
        reasons.append("partial_gold_doc_hit")
    if signal["has_signal"]:
        score += 12
        reasons.append(f"{category}_evidence_signal")
    if category == "budget":
        score += 8
        reasons.append("positive_budget_label_needed")
    elif category == "required_fields":
        score += 7
        reasons.append("positive_required_fields_label_needed")
    elif category == "multi_doc":
        score += 5
        reasons.append("positive_multi_doc_label_needed")
    if normalize_text(row.get("type")).upper() == "C":
        score += 3
        reasons.append("conversation_followup_answerable")
    if len(parse_doc_list(row.get("ground_truth_docs"))) > 1 and not doc_stats["all_gold_docs_hit"]:
        score -= 25
        reasons.append("multi_doc_missing_some_gold_docs")
    if not normalize_text(row.get("ground_truth_answer")):
        score -= 50
        reasons.append("missing_ground_truth_answer")
    return -score, " | ".join(reasons)


def select_rows(
    eval_rows: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    used_ids: set[str],
    limit: int,
    max_contexts: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eval_rows:
        qid = question_id(row)
        qtype = normalize_text(row.get("type")).upper()
        if not qid or qid in used_ids or qid not in predictions:
            continue
        if qtype not in {"A", "B", "C"}:
            continue
        pred = predictions[qid]
        doc_stats = doc_hit_stats(row, pred, max_contexts)
        signal = evidence_signal(row, pred, max_contexts)
        if not doc_stats["all_gold_docs_hit"]:
            continue
        if not signal["has_signal"]:
            continue
        enriched = dict(row)
        enriched["task_family"] = category_for(row)
        enriched["doc_hit_stats"] = doc_stats
        enriched["answerable_evidence_signal"] = signal
        _, reason = candidate_score(row, pred, max_contexts)
        enriched["selection_reason"] = reason
        buckets[enriched["task_family"]].append(enriched)

    for rows in buckets.values():
        rows.sort(key=lambda item: (candidate_score(item, predictions[question_id(item)], max_contexts)[0], question_id(item)))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for category, quota in CATEGORY_QUOTAS.items():
        for row in buckets.get(category, []):
            if sum(1 for item in selected if item["task_family"] == category) >= quota:
                break
            qid = question_id(row)
            if qid in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(qid)
            if len(selected) >= limit:
                return selected

    if len(selected) < limit:
        candidates: list[dict[str, Any]] = []
        for rows in buckets.values():
            candidates.extend(rows)
        candidates.sort(key=lambda item: (candidate_score(item, predictions[question_id(item)], max_contexts)[0], question_id(item)))
        for row in candidates:
            qid = question_id(row)
            if qid in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(qid)
            if len(selected) >= limit:
                break
    return selected


def compact_context(ctx: dict[str, Any], text_max_chars: int) -> dict[str, Any]:
    metadata = ctx.get("metadata") or {}
    return {
        "rank": ctx.get("rank"),
        "score": ctx.get("score"),
        "doc_id": ctx.get("doc_id") or metadata.get("doc_id") or "",
        "source_file": normalize_text(ctx.get("source_file") or ctx.get("filename") or metadata.get("source_file") or ""),
        "chunk_id": ctx.get("chunk_id") or metadata.get("chunk_id") or "",
        "source_store_id": ctx.get("source_store_id") or metadata.get("source_store_id") or "",
        "chunk_type": metadata.get("chunk_type") or ctx.get("chunk_type") or "",
        "fact_type": metadata.get("fact_type") or ctx.get("fact_type") or "",
        "section_path": metadata.get("section_path") or ctx.get("section_path") or "",
        "issuer": metadata.get("issuer") or "",
        "project_name": metadata.get("project_name") or "",
        "budget": metadata.get("budget") or "",
        "text": truncate(ctx.get("text") or "", text_max_chars),
    }


def source_store_targets(pred: dict[str, Any], row: dict[str, Any]) -> dict[str, set[str]]:
    ids: set[str] = set()
    doc_ids: set[str] = set()
    normalized_files: set[str] = set()
    for ctx in pred.get("retrieved_contexts") or []:
        metadata = ctx.get("metadata") or {}
        for value in [ctx.get("source_store_id"), metadata.get("source_store_id")]:
            if value:
                ids.add(str(value))
        for value in [ctx.get("doc_id"), metadata.get("doc_id")]:
            if value:
                doc_ids.add(str(value))
        source_file = ctx.get("source_file") or ctx.get("filename") or metadata.get("source_file")
        if source_file:
            normalized_files.add(normalize_key(source_file))
    for source_file in parse_doc_list(row.get("ground_truth_docs")):
        normalized_files.add(normalize_key(source_file))
    return {
        "source_store_ids": ids,
        "doc_ids": doc_ids,
        "normalized_source_files": normalized_files,
    }


def should_keep_source_store(row: dict[str, Any], targets: dict[str, set[str]]) -> bool:
    if str(row.get("source_store_id") or "") in targets["source_store_ids"]:
        return True
    if str(row.get("doc_id") or "") in targets["doc_ids"] or str(row.get("canonical_doc_id") or "") in targets["doc_ids"]:
        return True
    values = [row.get("source_file"), row.get("source_file_nfc"), row.get("doc_key"), row.get("canonical_doc_key")]
    normalized = {normalize_key(value) for value in values if value}
    return bool(normalized & targets["normalized_source_files"])


def compact_source_store(row: dict[str, Any], max_chars: int) -> dict[str, Any]:
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
            or key in {"document_summary", "fact_candidates", "computed_values", "evidence_sentences", "full_text"}
        )
        if not include:
            continue
        if key == "full_text":
            compact[key] = truncate(value, max_chars)
        else:
            compact[key] = truncate(value, 600) if isinstance(value, str) else value
    if "full_text" not in compact and row.get("full_text"):
        compact["full_text"] = truncate(row["full_text"], max_chars)
    return compact


def load_matched_source_store(
    path: Path,
    targets_by_qid: dict[str, dict[str, set[str]]],
    max_items: int,
    max_chars: int,
) -> dict[str, list[dict[str, Any]]]:
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            for qid, targets in targets_by_qid.items():
                if len(matches[qid]) >= max_items:
                    continue
                if should_keep_source_store(row, targets):
                    compact = compact_source_store(row, max_chars)
                    if compact:
                        matches[qid].append(compact)
    return dict(matches)


def gold_reference_from_eval(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_set": "canonical_eval_answerable_v5_for_peft",
        "question_type": normalize_text(row.get("type")),
        "difficulty": normalize_text(row.get("difficulty")),
        "source_docs": parse_doc_list(row.get("ground_truth_docs")),
        "metadata_filter": parse_structured(row.get("metadata_filter"), {}),
        "history": parse_structured(row.get("history"), []),
        "ground_truth_answer": normalize_text(row.get("ground_truth_answer")),
        "task_family": row.get("task_family") or "",
        "doc_hit_stats": row.get("doc_hit_stats") or {},
        "answerable_evidence_signal": row.get("answerable_evidence_signal") or {},
        "selection_reason": row.get("selection_reason") or "",
        "notes": (
            "This row is selected for positive answerable PEFT labeling. "
            "Write a concrete grounded answer when the provided evidence supports it. "
            "If gold_reference conflicts with retrieved_contexts/source_store, mark trainable=false."
        ),
    }


def build_prompt_text(bundle_name: str) -> str:
    return f"""# PEFT/SFT 정답형 라벨 확장 요청 프롬프트

너는 RFP 문서 기반 QA 시스템의 PEFT/SFT 학습 데이터를 만드는 검수 보조자다.

내가 첨부하는 JSONL 파일에는 각 문항별로 question, retrieved_contexts, source_store, gold_reference가 들어 있다.
목표는 PEFT/SFT 학습에 사용할 수 있는 **정답형 고품질 답변 라벨**을 만드는 것이다.

이번 파일은 답변불가 라벨을 늘리기 위한 것이 아니다.
이미 검색 결과 안에 정답 문서와 근거가 있을 가능성이 높은 문항만 골랐다.
따라서 가능한 한 "문서에서 확인할 수 없습니다"로 회피하지 말고, 근거가 충분하면 구체적인 정답을 작성한다.

중요 규칙:
1. 반드시 첨부된 retrieved_contexts와 source_store 안의 정보만 사용한다.
2. gold_reference.ground_truth_answer는 참고 정답이다. 단, 실제 답변은 retrieved_contexts/source_store에서 근거가 확인되는 범위에서만 작성한다.
3. 문서 근거가 충분하면 trainable=true로 둔다.
4. 근거가 부족하거나 gold_reference와 context/source_store가 충돌하면 trainable=false, needs_human_review=true로 표시한다.
5. 답변불가 라벨은 최소화한다. 정말 근거가 없을 때만 "문서에서 확인할 수 없습니다"라고 답한다.
6. 금액, 날짜, 기간, 공고번호, 기관명, 사업명은 원문 표현을 우선 보존한다.
7. 금액이 "천원" 단위이면 원문 금액과 원 단위 환산값을 함께 적는다.
8. 여러 문서를 비교하는 질문이면 문서별로 나눠서 답변한다.
9. 답변에는 반드시 근거 문서명과 근거 문장을 포함한다.
10. source_store와 retrieved_contexts가 충돌하면 하나로 단정하지 말고 충돌 사실을 표시하고 trainable=false로 둔다.
11. 빈 답변은 절대 만들지 않는다.

출력은 반드시 JSONL 형식으로 작성한다.
각 줄은 하나의 JSON 객체여야 한다.
마크다운 표나 별도 설명은 출력하지 않는다.

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

answer 작성 규칙:
- 예산 계산형은 "문서별 금액 / 계산 과정 / 최종 답변 / 근거" 형식을 우선 사용한다.
- 제출서류/자격요건/필수항목 질문은 항목을 명확히 구분한다.
- 다중 문서 질문은 문서별 답을 먼저 쓰고 마지막에 비교/합산 결론을 쓴다.
- 문서 근거가 있으면 확인 불가로 회피하지 않는다.
- 불확실한 경우 단정하지 않는다.

이제 {bundle_name}의 모든 question_id에 대해 정답형 라벨 JSONL을 작성하라.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--source-store", type=Path, default=DEFAULT_SOURCE_STORE)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--canonical-count", type=int, default=25)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--max-retrieved-contexts", type=int, default=12)
    parser.add_argument("--context-text-max-chars", type=int, default=1600)
    parser.add_argument("--max-source-items", type=int, default=6)
    parser.add_argument("--source-text-max-chars", type=int, default=1200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    predictions = {question_id(row): row for row in read_jsonl(args.predictions)}
    eval_rows = load_eval_rows(args.eval_dir, args.canonical_count)
    used_ids = load_used_ids(
        [
            Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl"),
            Path("outputs/peft/question_context_bundle_for_labeling.jsonl"),
            Path("outputs/peft/gpt_handoff/question_context_bundle_for_labeling_extra_50.jsonl"),
            Path("outputs/peft/v3_extra50_salvaged/combined_question_context_bundle.jsonl"),
            Path("outputs/peft/v4_extra50_balanced/combined_question_context_bundle.jsonl"),
        ]
    )
    selected = select_rows(eval_rows, predictions, used_ids, args.limit, args.max_retrieved_contexts)
    if len(selected) < args.limit:
        raise SystemExit(f"Only selected {len(selected)} rows; expected {args.limit}")

    targets_by_qid = {
        question_id(row): source_store_targets(predictions[question_id(row)], row)
        for row in selected
    }
    source_store_by_qid = load_matched_source_store(
        args.source_store,
        targets_by_qid,
        max_items=args.max_source_items,
        max_chars=args.source_text_max_chars,
    )

    bundle_rows: list[dict[str, Any]] = []
    for row in selected:
        qid = question_id(row)
        pred = predictions[qid]
        contexts = [
            compact_context(context, args.context_text_max_chars)
            for context in (pred.get("retrieved_contexts") or [])[: args.max_retrieved_contexts]
        ]
        bundle_rows.append(
            {
                "question_id": qid,
                "question": normalize_text(row.get("question")),
                "task_family": row.get("task_family") or "",
                "question_type": normalize_text(row.get("type")),
                "difficulty": normalize_text(row.get("difficulty")),
                "source_eval_file": row.get("source_eval_file"),
                "source_docs": parse_doc_list(row.get("ground_truth_docs")),
                "gold_reference": gold_reference_from_eval(row),
                "retrieved_docs_top5": [
                    normalize_text(context.get("source_file") or context.get("filename") or (context.get("metadata") or {}).get("source_file"))
                    for context in (pred.get("retrieved_contexts") or [])[:5]
                ],
                "retrieved_contexts": contexts,
                "source_store": source_store_by_qid.get(qid, []),
                "labeling_instruction": (
                    "정답형 라벨을 작성하세요. 제공된 evidence로 ground_truth_answer를 뒷받침할 수 있으면 "
                    "구체적인 답변을 작성하고 trainable=true로 둡니다. 근거가 부족하거나 충돌하면 trainable=false로 둡니다. "
                    f"선정 이유: {row.get('selection_reason') or ''}"
                ),
            }
        )

    write_jsonl(args.output, bundle_rows)
    args.prompt.parent.mkdir(parents=True, exist_ok=True)
    args.prompt.write_text(build_prompt_text(args.output.name), encoding="utf-8")

    manifest = {
        "bundle_path": str(args.output),
        "prompt_path": str(args.prompt),
        "readme_path": str(args.readme),
        "predictions": str(args.predictions),
        "source_store": str(args.source_store),
        "eval_dir": str(args.eval_dir),
        "question_count": len(bundle_rows),
        "excluded_existing_ids": len(used_ids),
        "task_family_counts": dict(Counter(row["task_family"] for row in bundle_rows)),
        "question_type_counts": dict(Counter(row["question_type"] for row in bundle_rows)),
        "difficulty_counts": dict(Counter(row["difficulty"] for row in bundle_rows)),
        "question_ids": [row["question_id"] for row in bundle_rows],
        "questions_without_source_store": [
            row["question_id"] for row in bundle_rows if not row.get("source_store")
        ],
        "selection_policy": {
            "include_types": ["A", "B", "C"],
            "exclude_types": ["D", "E"],
            "requires_ground_truth_answer": True,
            "requires_all_gold_docs_hit_in_top_contexts": args.max_retrieved_contexts,
            "requires_question_type_evidence_signal": True,
            "purpose": "positive answerable PEFT labels, not refusal-heavy labels",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = [
        "# GPT Handoff: Answerable v5 Label Expansion",
        "",
        "## Files",
        f"- bundle: `{args.output}`",
        f"- prompt: `{args.prompt}`",
        f"- manifest: `{args.manifest}`",
        "",
        "## Purpose",
        "- v3/v4에서 답변불가/부분답변 라벨이 많아져 성능이 오르지 않았습니다.",
        "- 이번 v5 bundle은 정답 문서가 검색 결과에 있고, 질문 유형별 evidence 신호가 있는 answerable 문항만 고릅니다.",
        "- GPT에는 이 bundle과 prompt를 같이 주고, 가능한 한 정답형 라벨을 작성하게 합니다.",
        "",
        "## Selection Summary",
        f"- question_count: {len(bundle_rows)}",
        f"- task_family_counts: {manifest['task_family_counts']}",
        f"- question_type_counts: {manifest['question_type_counts']}",
        f"- questions_without_source_store: {manifest['questions_without_source_store']}",
        "",
        "## After GPT returns labels",
        "- Save the returned JSONL as `outputs/peft/answer_labels_answerable_v5_50.jsonl`.",
        "- Then validate the JSONL and convert trainable rows to a new v5 SFT dataset.",
    ]
    args.readme.write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"[OK] wrote {len(bundle_rows)} rows to {args.output}")
    print(f"[OK] wrote prompt to {args.prompt}")
    print(f"[OK] wrote manifest to {args.manifest}")
    print(json.dumps(manifest["task_family_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
