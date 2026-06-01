from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_GOLD = Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl")
DEFAULT_PREDICTIONS = Path(
    "outputs/predictions/"
    "104_best_dense_qdecomp_docscore_targetaware_kure_chroma_chunks_v2_690_phase34_gold50.jsonl"
)
DEFAULT_CHUNKS = Path("indexes/chroma_kure_v1_chunks_v2_690/chunks.json")
DEFAULT_SOURCE_STORE = Path("data/processed/source_store_v2_690.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/diagnostics/source_store_gold_conflict_690")

AMOUNT_RE = re.compile(
    r"(?<![\d.])"
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*"
    r"(조\s*원|억원|억\s*원|억|백만원|백만\s*원|천만원|천만\s*원|만원|천원|원)"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def compact_doc_key(value: Any) -> str:
    text = nfc(value)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def amount_to_won(number_text: str, unit_text: str) -> int | None:
    try:
        number = float(number_text.replace(",", ""))
    except ValueError:
        return None

    unit = re.sub(r"\s+", "", unit_text)
    if unit.startswith("조"):
        multiplier = 1_000_000_000_000
    elif unit.startswith("억"):
        multiplier = 100_000_000
    elif unit.startswith("천만"):
        multiplier = 10_000_000
    elif unit.startswith("백만"):
        multiplier = 1_000_000
    elif unit.startswith("만"):
        multiplier = 10_000
    elif unit.startswith("천"):
        multiplier = 1_000
    else:
        multiplier = 1
    return int(round(number * multiplier))


def extract_amounts(text: Any) -> list[int]:
    found: list[int] = []
    for match in AMOUNT_RE.finditer(nfc(text)):
        won = amount_to_won(match.group(1), match.group(2))
        if won is not None:
            found.append(won)
    return sorted(set(found))


def format_won(values: list[int] | set[int]) -> str:
    return ", ".join(f"{int(value):,}원" for value in sorted(values)) if values else ""


def budget_gold_amounts(row: dict[str, Any]) -> list[int]:
    amounts: set[int] = set()
    budget = row.get("budget_gold") or {}
    total = as_int(budget.get("total_krw"))
    if total:
        amounts.add(total)
    for item in budget.get("items") or []:
        amount = as_int(item.get("amount_krw"))
        if amount:
            amounts.add(amount)
    return sorted(amounts)


def excluded_gold_amounts(row: dict[str, Any]) -> list[int]:
    budget = row.get("budget_gold") or {}
    values: set[int] = set()
    for raw in budget.get("excluded_budget_candidates") or []:
        values.update(extract_amounts(raw))
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            for key in ("amount_krw", "final_budget_krw", "budget_krw"):
                amount = as_int(parsed.get(key))
                if amount:
                    values.add(amount)
    return sorted(values)


def source_docs(row: dict[str, Any]) -> list[str]:
    docs = list(row.get("source_docs") or [])
    budget = row.get("budget_gold") or {}
    for item in budget.get("items") or []:
        if item.get("source_file"):
            docs.append(item["source_file"])
    for ref in row.get("evidence_refs") or []:
        if ref.get("source_file"):
            docs.append(ref["source_file"])
    seen: set[str] = set()
    unique: list[str] = []
    for doc in docs:
        key = compact_doc_key(doc)
        if key and key not in seen:
            seen.add(key)
            unique.append(nfc(doc))
    return unique


def top_contexts(row: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
    contexts = list(row.get("retrieved_contexts") or [])
    return sorted(contexts, key=lambda x: int(x.get("rank") or 999))[:top_k]


def collect_targets(
    gold_rows: list[dict[str, Any]], pred_rows: list[dict[str, Any]]
) -> tuple[set[str], set[str], set[str]]:
    qids = {row.get("id") for row in pred_rows}
    target_source_keys: set[str] = set()
    target_source_store_ids: set[str] = set()
    target_chunk_ids: set[str] = set()

    for row in gold_rows:
        if row.get("id") not in qids:
            continue
        for doc in source_docs(row):
            target_source_keys.add(compact_doc_key(doc))
        for ref in row.get("evidence_refs") or []:
            if ref.get("chunk_id"):
                target_chunk_ids.add(str(ref["chunk_id"]))

    for pred in pred_rows:
        for ctx in top_contexts(pred):
            if ctx.get("chunk_id"):
                target_chunk_ids.add(str(ctx["chunk_id"]))
            if ctx.get("filename"):
                target_source_keys.add(compact_doc_key(ctx["filename"]))
            metadata = ctx.get("metadata") or {}
            source_store_id = metadata.get("source_store_id") or ctx.get("source_store_id")
            if source_store_id:
                target_source_store_ids.add(str(source_store_id))
    return target_source_keys, target_source_store_ids, target_chunk_ids


def load_relevant_chunks(
    path: Path, target_source_keys: set[str], target_chunk_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    with path.open("r", encoding="utf-8") as f:
        rows = json.load(f)

    by_id: dict[str, dict[str, Any]] = {}
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        metadata = row.get("metadata") or {}
        chunk_id = str(row.get("chunk_id") or "")
        source_key = compact_doc_key(metadata.get("source_file"))
        if chunk_id in target_chunk_ids or source_key in target_source_keys:
            slim = {
                "chunk_id": chunk_id,
                "doc_id": row.get("doc_id", ""),
                "text": row.get("text", ""),
                "metadata": metadata,
            }
            by_id[chunk_id] = slim
            if source_key:
                by_source[source_key].append(slim)
    return by_id, by_source


def slim_source_record(row: dict[str, Any]) -> dict[str, Any]:
    full_text = nfc(row.get("full_text"))
    return {
        "source_store_id": row.get("source_store_id", ""),
        "doc_id": row.get("doc_id", ""),
        "canonical_doc_id": row.get("canonical_doc_id", ""),
        "source_file": row.get("source_file_nfc") or row.get("source_file", ""),
        "source_file_raw": row.get("source_file", ""),
        "final_budget": row.get("final_budget", ""),
        "final_budget_krw": row.get("final_budget_krw", ""),
        "final_budget_status": row.get("final_budget_status", ""),
        "final_budget_type": row.get("final_budget_type", ""),
        "budget_value_role": row.get("budget_value_role", ""),
        "budget_answer_enabled": row.get("budget_answer_enabled", ""),
        "budget_policy_note": row.get("budget_policy_note", ""),
        "chunk_type": row.get("chunk_type", ""),
        "section_type": row.get("section_type", ""),
        "full_text_sample": full_text[:600],
        "full_text_amounts": extract_amounts(full_text[:4000]),
    }


def load_relevant_source_store(
    path: Path, target_source_keys: set[str], target_source_store_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            source_store_id = str(row.get("source_store_id") or "")
            source_key = compact_doc_key(row.get("source_file_nfc") or row.get("source_file"))
            if source_store_id not in target_source_store_ids and source_key not in target_source_keys:
                continue
            slim = slim_source_record(row)
            if source_store_id:
                by_id[source_store_id] = slim
            if source_key:
                by_source[source_key].append(slim)
    return by_id, by_source


def values_from_source_records(records: list[dict[str, Any]]) -> set[int]:
    values: set[int] = set()
    for record in records:
        direct = as_int(record.get("final_budget_krw"))
        if direct:
            values.add(direct)
        values.update(extract_amounts(record.get("final_budget")))
    return values


def values_from_contexts(contexts: list[dict[str, Any]]) -> tuple[set[int], set[int]]:
    metadata_values: set[int] = set()
    text_values: set[int] = set()
    for ctx in contexts:
        metadata = ctx.get("metadata") or {}
        for key in ("budget", "final_budget", "amounts"):
            metadata_values.update(extract_amounts(metadata.get(key)))
        text_values.update(extract_amounts(ctx.get("text")))
    return metadata_values, text_values


def values_from_chunks(chunks: list[dict[str, Any]]) -> set[int]:
    values: set[int] = set()
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        values.update(extract_amounts(metadata.get("budget")))
        values.update(extract_amounts(metadata.get("amounts")))
        values.update(extract_amounts(chunk.get("text")))
    return values


def source_records_for_docs(
    docs: list[str], source_by_key: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        for record in source_by_key.get(compact_doc_key(doc), []):
            key = str(record.get("source_store_id") or id(record))
            if key not in seen:
                seen.add(key)
                records.append(record)
    return records


def chunks_for_docs(
    docs: list[str], chunks_by_key: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        for chunk in chunks_by_key.get(compact_doc_key(doc), []):
            key = str(chunk.get("chunk_id") or id(chunk))
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)
    return chunks


def diagnose_case(
    *,
    gold_values: set[int],
    excluded_values: set[int],
    source_final_values: set[int],
    retrieved_metadata_values: set[int],
    retrieved_text_values: set[int],
    chunk_values: set[int],
    gold_doc_hit: bool,
    gold_evidence_present_count: int,
    gold_evidence_total: int,
) -> list[str]:
    tags: list[str] = []
    context_values = retrieved_metadata_values | retrieved_text_values
    if gold_doc_hit and not (gold_values & context_values):
        tags.append("정답 문서는 top5에 있으나 정답 금액이 context에 없음")
    if not gold_doc_hit:
        tags.append("정답 문서가 top5에 없음")
    if gold_evidence_total and gold_evidence_present_count == 0:
        tags.append("gold evidence chunk_id가 현재 690 chunks에 없음")
    elif gold_evidence_total and gold_evidence_present_count < gold_evidence_total:
        tags.append("gold evidence chunk_id 일부만 현재 690 chunks에 있음")
    if source_final_values and not (source_final_values & gold_values):
        if source_final_values & excluded_values:
            tags.append("source_store final_budget이 gold의 제외 후보 금액과 겹침")
        else:
            tags.append("source_store final_budget이 gold 금액과 다름")
    if retrieved_metadata_values and not (retrieved_metadata_values & gold_values):
        if retrieved_metadata_values & excluded_values:
            tags.append("retrieved chunk metadata budget이 제외 후보 금액과 겹침")
        else:
            tags.append("retrieved chunk metadata budget이 gold 금액과 다름")
    if chunk_values and gold_values and not (chunk_values & gold_values):
        tags.append("현재 corpus의 해당 문서 chunks에서 gold 금액을 찾지 못함")
    if not tags:
        tags.append("명확한 예산 충돌 없음")
    return tags


def make_row(
    gold: dict[str, Any],
    pred: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    chunks_by_source: dict[str, list[dict[str, Any]]],
    source_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    qid = str(gold.get("id"))
    docs = source_docs(gold)
    gold_values = set(budget_gold_amounts(gold))
    excluded_values = set(excluded_gold_amounts(gold))
    contexts = top_contexts(pred)
    top_docs = [nfc(ctx.get("filename")) for ctx in contexts]
    top_doc_keys = {compact_doc_key(doc) for doc in top_docs}
    gold_doc_keys = {compact_doc_key(doc) for doc in docs}
    gold_doc_hit = bool(top_doc_keys & gold_doc_keys)

    source_records = source_records_for_docs(docs, source_by_source)
    source_final_values = values_from_source_records(source_records)
    source_final_statuses = sorted(
        {
            str(record.get("final_budget_status") or "")
            for record in source_records
            if record.get("final_budget_status")
        }
    )
    source_budget_roles = sorted(
        {
            str(record.get("budget_value_role") or "")
            for record in source_records
            if record.get("budget_value_role")
        }
    )

    doc_chunks = chunks_for_docs(docs, chunks_by_source)
    current_doc_ids = sorted({str(chunk.get("doc_id") or "") for chunk in doc_chunks if chunk.get("doc_id")})
    current_chunk_values = values_from_chunks(doc_chunks)
    retrieved_metadata_values, retrieved_text_values = values_from_contexts(contexts)

    gold_evidence_ids = [str(ref.get("chunk_id")) for ref in gold.get("evidence_refs") or [] if ref.get("chunk_id")]
    gold_evidence_present = [chunk_id for chunk_id in gold_evidence_ids if chunk_id in chunks_by_id]
    retrieved_chunk_ids = [str(ctx.get("chunk_id") or "") for ctx in contexts]
    retrieved_source_store_ids = sorted(
        {
            str((ctx.get("metadata") or {}).get("source_store_id") or ctx.get("source_store_id") or "")
            for ctx in contexts
            if (ctx.get("metadata") or {}).get("source_store_id") or ctx.get("source_store_id")
        }
    )

    tags = diagnose_case(
        gold_values=gold_values,
        excluded_values=excluded_values,
        source_final_values=source_final_values,
        retrieved_metadata_values=retrieved_metadata_values,
        retrieved_text_values=retrieved_text_values,
        chunk_values=current_chunk_values,
        gold_doc_hit=gold_doc_hit,
        gold_evidence_present_count=len(gold_evidence_present),
        gold_evidence_total=len(gold_evidence_ids),
    )

    return {
        "question_id": qid,
        "question": gold.get("question", ""),
        "task_family": gold.get("task_family", ""),
        "gold_source_docs": " | ".join(docs),
        "gold_amounts": format_won(gold_values),
        "gold_excluded_amounts": format_won(excluded_values),
        "retrieved_top5_docs": " | ".join(top_docs),
        "retrieved_chunk_ids": " | ".join(retrieved_chunk_ids),
        "retrieved_source_store_ids": " | ".join(retrieved_source_store_ids),
        "retrieved_metadata_budget_amounts": format_won(retrieved_metadata_values),
        "retrieved_text_amounts": format_won(retrieved_text_values),
        "source_store_final_budget_amounts": format_won(source_final_values),
        "source_store_final_budget_statuses": " | ".join(source_final_statuses),
        "source_store_budget_value_roles": " | ".join(source_budget_roles),
        "current_corpus_doc_ids_for_gold_docs": " | ".join(current_doc_ids),
        "current_corpus_amounts_for_gold_docs": format_won(current_chunk_values),
        "gold_evidence_chunk_total": len(gold_evidence_ids),
        "gold_evidence_chunk_present_in_current_chunks": len(gold_evidence_present),
        "gold_doc_hit_top5": gold_doc_hit,
        "diagnosis": " ; ".join(tags),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    tag_counter: Counter[str] = Counter()
    for row in rows:
        for tag in row["diagnosis"].split(" ; "):
            tag_counter[tag] += 1

    lines: list[str] = [
        "# Source Store / Gold 예산 충돌 진단",
        "",
        "이 리포트는 기존 eval 로직을 변경하지 않고, 예산 gold 값과 현재 690 corpus의 retrieval/source_store/sidecar 값이 서로 맞는지 확인한 참고용 진단입니다.",
        "",
        "## 요약",
        "",
        f"- 분석 대상 예산 문항: {len(rows)}개",
    ]
    for tag, count in tag_counter.most_common():
        lines.append(f"- {tag}: {count}건")

    lines.extend(
        [
            "",
            "## 문항별 요약",
            "",
            "| question_id | gold 금액 | source_store final_budget | retrieved metadata budget | evidence id 상태 | 진단 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {qid} | {gold} | {source} | {retrieved} | {present}/{total} | {diagnosis} |".format(
                qid=row["question_id"],
                gold=row["gold_amounts"] or "-",
                source=row["source_store_final_budget_amounts"] or "-",
                retrieved=row["retrieved_metadata_budget_amounts"] or "-",
                present=row["gold_evidence_chunk_present_in_current_chunks"],
                total=row["gold_evidence_chunk_total"],
                diagnosis=row["diagnosis"],
            )
        )

    lines.extend(
        [
            "",
            "## 해석 방법",
            "",
            "- `정답 문서는 top5에 있으나 정답 금액이 context에 없음`: 검색은 문서 단위로는 맞았지만, LLM에 들어간 chunk/metadata에는 gold 금액이 없다는 뜻입니다.",
            "- `source_store final_budget이 gold 금액과 다름`: source_store가 정리해 둔 최종 예산값 자체가 gold와 다르므로, generation context 상단에 넣으면 모델이 틀린 값을 더 신뢰할 수 있습니다.",
            "- `gold evidence chunk_id가 현재 690 chunks에 없음`: gold가 참조하는 chunk id와 현재 corpus chunk id가 달라졌다는 뜻입니다. 같은 문서명이라도 재처리/재청킹으로 doc_id가 바뀌었을 가능성이 큽니다.",
            "- `retrieved chunk metadata budget이 gold 금액과 다름`: chunk metadata의 `budget` 필드가 gold와 다른 금액을 대표값처럼 들고 있다는 뜻입니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    gold_rows = read_jsonl(args.gold)
    pred_rows = read_jsonl(args.predictions)
    pred_by_id = {str(row.get("id")): row for row in pred_rows}
    budget_gold_rows = [
        row for row in gold_rows if row.get("id") in pred_by_id and budget_gold_amounts(row)
    ]

    target_source_keys, target_source_store_ids, target_chunk_ids = collect_targets(gold_rows, pred_rows)
    chunks_by_id, chunks_by_source = load_relevant_chunks(
        args.chunks, target_source_keys, target_chunk_ids
    )
    _, source_by_source = load_relevant_source_store(
        args.source_store, target_source_keys, target_source_store_ids
    )

    rows = [
        make_row(
            gold=row,
            pred=pred_by_id[str(row["id"])],
            chunks_by_id=chunks_by_id,
            chunks_by_source=chunks_by_source,
            source_by_source=source_by_source,
        )
        for row in budget_gold_rows
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "source_store_gold_conflict_budget_50.csv", rows)
    write_jsonl(args.output_dir / "source_store_gold_conflict_budget_50.jsonl", rows)
    write_report(args.output_dir / "source_store_gold_conflict_budget_50.md", rows)
    print(f"wrote {len(rows)} rows to {args.output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Phase 3/4 budget gold values against retrieved contexts, chunks, and source_store final values."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--source-store", type=Path, default=DEFAULT_SOURCE_STORE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
