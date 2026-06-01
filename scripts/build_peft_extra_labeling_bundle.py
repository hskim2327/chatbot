#!/usr/bin/env python3
"""Build an extra PEFT labeling bundle from eval CSVs and retrieval predictions.

This is separate from the Phase3 gold labeling bundle. It intentionally uses
the broader canonical eval set so we can expand SFT data without re-labeling
the existing 50 Phase3 rows.
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
DEFAULT_OUTPUT = Path("outputs/peft/gpt_handoff/question_context_bundle_for_labeling_extra_50.jsonl")
DEFAULT_MANIFEST = Path("outputs/peft/gpt_handoff/question_context_bundle_for_labeling_extra_50_manifest.json")
DEFAULT_PROMPT = Path("outputs/peft/gpt_handoff/label_expansion_prompt_extra_50.md")

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
    "required_fields": 14,
    "budget": 12,
    "unanswerable_or_guard": 12,
    "multi_doc": 8,
    "general": 4,
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
        if not path.exists():
            continue
        for row in read_jsonl(path):
            qid = question_id(row)
            if qid:
                used.add(qid)
    return used


def categories_for(row: dict[str, Any]) -> list[str]:
    question = normalize_text(row.get("question"))
    qtype = normalize_text(row.get("type")).upper()
    categories: list[str] = []
    if re.search(r"제출서류|참가자격|자격요건|평가항목|평가기준|입찰마감|마감일|도입|내역|나열|모두|필수|원본|라이선스|수량|서류", question):
        categories.append("required_fields")
    if re.search(r"예산|금액|합계|차액|얼마|더하면|비율|작은|큰|총액|사업비|원", question):
        categories.append("budget")
    if qtype in {"D", "E"} or re.search(r"반드시|필수로|해야 합니까|없는|확인|실제로|진짜|맞나요", question):
        categories.append("unanswerable_or_guard")
    if qtype == "B" or len(parse_doc_list(row.get("ground_truth_docs"))) > 1:
        categories.append("multi_doc")
    if not categories:
        categories.append("general")
    return categories


def primary_category(categories: list[str]) -> str:
    # Keep the primary label closer to the training gap we want to fill.
    # D/E or explicit guard questions should not be hidden under required_fields
    # just because they mention "필수", "수량", or "내역".
    for category in ("unanswerable_or_guard", "required_fields", "budget", "multi_doc", "general"):
        if category in categories:
            return category
    return "general"


def priority_score(row: dict[str, Any], categories: list[str]) -> tuple[int, str]:
    question = normalize_text(row.get("question"))
    score = 0
    reasons: list[str] = []
    if "required_fields" in categories:
        score += 5
        reasons.append("case_analysis:wrong_field/missing_required_field 보강")
    if "budget" in categories:
        score += 4
        reasons.append("case_analysis:weak_budget_format/missing_calculation 보강")
    if "unanswerable_or_guard" in categories:
        score += 4
        reasons.append("case_analysis:hallucinated_value/under_refusal 보강")
    if "multi_doc" in categories:
        score += 3
        reasons.append("case_analysis:lost_source_doc/multi_doc_mixing 보강")
    if re.search(r"모두|나열|구체|수량|필수|원본|계산|합계|차액", question):
        score += 2
        reasons.append("정확한 필드 추출/포맷 훈련용")
    if normalize_text(row.get("type")).upper() in {"D", "E"}:
        score += 2
        reasons.append("답변불가/오타 질문 가드레일 훈련용")
    return -score, " | ".join(reasons)


def select_rows(eval_rows: list[dict[str, Any]], prediction_ids: set[str], used_ids: set[str], limit: int) -> list[dict[str, Any]]:
    candidates_by_primary: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eval_rows:
        qid = question_id(row)
        if not qid or qid not in prediction_ids or qid in used_ids:
            continue
        categories = categories_for(row)
        _, reason = priority_score(row, categories)
        enriched = dict(row)
        enriched["labeling_categories"] = categories
        enriched["primary_labeling_category"] = primary_category(categories)
        enriched["selection_reason"] = reason
        candidates_by_primary[enriched["primary_labeling_category"]].append(enriched)

    for category, rows in candidates_by_primary.items():
        rows.sort(key=lambda item: (priority_score(item, item["labeling_categories"])[0], question_id(item)))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for category, quota in CATEGORY_QUOTAS.items():
        for row in candidates_by_primary.get(category, []):
            if len([item for item in selected if item["primary_labeling_category"] == category]) >= quota:
                break
            qid = question_id(row)
            if qid in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(qid)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        all_candidates: list[dict[str, Any]] = []
        for rows in candidates_by_primary.values():
            all_candidates.extend(rows)
        all_candidates.sort(key=lambda item: (priority_score(item, item["labeling_categories"])[0], question_id(item)))
        for row in all_candidates:
            qid = question_id(row)
            if qid in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(qid)
            if len(selected) >= limit:
                break

    return selected[:limit]


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
    files: set[str] = set()
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
            files.add(normalize_text(source_file))
            normalized_files.add(normalize_key(source_file))
    for source_file in parse_doc_list(row.get("ground_truth_docs")):
        files.add(source_file)
        normalized_files.add(normalize_key(source_file))
    return {
        "source_store_ids": ids,
        "doc_ids": doc_ids,
        "source_files": files,
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
        )
        if not include:
            continue
        if key == "full_text":
            compact[key] = truncate(value, max_chars)
        else:
            compact[key] = truncate(value, 500) if isinstance(value, str) else value
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
        "source_set": "canonical_eval_extra_for_peft",
        "question_type": normalize_text(row.get("type")),
        "difficulty": normalize_text(row.get("difficulty")),
        "source_docs": parse_doc_list(row.get("ground_truth_docs")),
        "metadata_filter": parse_structured(row.get("metadata_filter"), {}),
        "history": parse_structured(row.get("history"), []),
        "ground_truth_answer": normalize_text(row.get("ground_truth_answer")),
        "labeling_categories": row.get("labeling_categories") or [],
        "selection_reason": row.get("selection_reason") or "",
        "notes": (
            "This row is selected for extra PEFT labeling based on GPT regression analysis. "
            "Use retrieved_contexts/source_store as evidence; ground_truth_docs are only document identity hints."
        ),
    }


def build_prompt_text() -> str:
    return """# PEFT/SFT 라벨 데이터 확장 요청 프롬프트

너는 RFP 문서 기반 QA 시스템의 PEFT/SFT 학습 데이터를 만드는 검수 보조자다.

내가 첨부하는 JSONL 파일에는 각 문항별로 question, retrieved_contexts, source_store, gold_reference가 들어 있다.
목표는 PEFT/SFT 학습에 바로 사용할 수 있는 고품질 정답 답변 JSONL을 만드는 것이다.

중요 규칙:
1. 반드시 첨부된 retrieved_contexts와 source_store 안의 정보만 사용한다.
2. 문서에 없는 내용은 추측하지 않는다.
3. 답을 알 수 없으면 "문서에서 확인할 수 없습니다"라고 답한다.
4. 빈 답변을 만들지 않는다. 근거가 부족하면 확인 불가 답변과 부족한 정보를 분리해 쓴다.
5. 금액, 날짜, 기간, 공고번호, 기관명, 사업명은 원문 표현을 우선 보존한다.
6. 금액이 "천원" 단위이면 원문 금액과 원 단위 환산값을 함께 적는다.
7. 여러 문서를 비교하는 질문이면 문서별로 나눠서 답변한다.
8. 답변에는 반드시 근거 문서명과 근거 문장을 포함한다.
9. source_store와 retrieved_contexts가 충돌하면 하나로 단정하지 말고 충돌 사실을 표시한다.
10. gold_reference는 참고 구조다. 실제 답변은 retrieved_contexts/source_store 근거와 충돌하지 않는 범위에서 작성한다.
11. 학습에 넣기 위험한 문항은 needs_human_review=true, trainable=false로 표시한다.

이번 추가 50문항은 PEFT 사례분석 결과를 반영해 required_fields, budget 계산형, unanswerable/guard, multi_doc 유형을 우선 포함했다.

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
- 문서에 없는 값을 물으면 "문서에서 확인할 수 없습니다"와 "확인 가능한 근거", "부족한 정보"를 함께 쓴다.
- 불확실한 경우 단정하지 않는다.

이제 question_context_bundle_for_labeling_extra_50.jsonl의 모든 question_id에 대해 정답 답변을 JSONL로 작성하라.
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
    parser.add_argument("--max-retrieved-contexts", type=int, default=10)
    parser.add_argument("--context-text-max-chars", type=int, default=1400)
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
        ]
    )
    selected = select_rows(eval_rows, set(predictions), used_ids, args.limit)
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
                "task_family": row.get("primary_labeling_category") or "",
                "labeling_categories": row.get("labeling_categories") or [],
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
                    "이 항목의 answer를 작성하되, 제공된 retrieved_contexts/source_store 안의 근거만 사용하세요. "
                    "근거가 충돌하거나 부족하면 needs_human_review=true로 표시하세요. "
                    f"선정 이유: {row.get('selection_reason') or ''}"
                ),
            }
        )

    write_jsonl(args.output, bundle_rows)
    args.prompt.parent.mkdir(parents=True, exist_ok=True)
    args.prompt.write_text(build_prompt_text(), encoding="utf-8")
    manifest = {
        "bundle_path": str(args.output),
        "prompt_path": str(args.prompt),
        "predictions": str(args.predictions),
        "source_store": str(args.source_store),
        "eval_dir": str(args.eval_dir),
        "question_count": len(bundle_rows),
        "excluded_existing_ids": len(used_ids),
        "category_counts": Counter(cat for row in bundle_rows for cat in row["labeling_categories"]),
        "primary_category_counts": Counter(row["task_family"] for row in bundle_rows),
        "question_ids": [row["question_id"] for row in bundle_rows],
        "questions_without_source_store": [
            row["question_id"] for row in bundle_rows if not row.get("source_store")
        ],
        "selection_basis": "GPT PEFT regression analysis: hallucinated_value, lost_source_doc, wrong_field, weak_budget_format, required_fields",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=dict) + "\n", encoding="utf-8")
    print(f"[OK] wrote {len(bundle_rows)} rows to {args.output}")
    print(f"[OK] wrote prompt to {args.prompt}")
    print(f"[OK] wrote manifest to {args.manifest}")
    print(json.dumps(manifest["primary_category_counts"], ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
