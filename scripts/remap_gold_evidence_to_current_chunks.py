from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_GOLD = Path("eval/evaluation/data/rfp_domain_gold_sample.jsonl")
DEFAULT_CHUNKS = Path("indexes/chroma_kure_v1_chunks_v2_690/chunks.json")
DEFAULT_OUTPUT_DIR = Path("outputs/diagnostics/evidence_remap_690")

DOC_KEY_PUNCT_RE = re.compile(r"[\s_·\-\[\]\(\\){}.,/\\\"'「」『』:;]+")
AMOUNT_RE = re.compile(
    r"(?<![\d.])"
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*"
    r"(조\s*원|억원|억\s*원|억|백만원|백만\s*원|천만원|천만\s*원|만원|천원|원)"
)

QUESTION_TYPE_TERMS = {
    "budget": (
        "사업예산",
        "사업 예산",
        "사업비",
        "총사업비",
        "총 사업비",
        "예산",
        "금액",
        "기초금액",
        "추정가격",
        "배정예산",
        "입찰금액",
        "price",
        "budget",
        "amount",
    ),
    "date_or_period": (
        "사업기간",
        "계약기간",
        "수행기간",
        "제출마감",
        "입찰마감",
        "마감일",
        "기간",
        "일정",
        "deadline",
        "duration",
        "period",
    ),
    "qualification": (
        "참가자격",
        "참가 자격",
        "입찰자격",
        "자격",
        "실적",
        "공동수급",
        "제한요건",
        "qualification",
        "eligibility",
    ),
    "submission_documents": (
        "제출서류",
        "제출 서류",
        "구비서류",
        "제안서",
        "제출물",
        "서식",
        "submission",
        "document",
    ),
    "required_fields": (
        "사업명",
        "발주기관",
        "공고번호",
        "담당자",
        "사업개요",
        "필수",
        "required",
        "identity",
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
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
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def normalize_doc_key(value: Any) -> str:
    text = nfc(value).strip()
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


def amount_to_won(number_text: str, unit_text: str) -> int:
    number = float(number_text.replace(",", ""))
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


def extract_amounts(text: Any) -> set[int]:
    values: set[int] = set()
    for number, unit in AMOUNT_RE.findall(nfc(text)):
        values.add(amount_to_won(number, unit))
    return values


def safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def gold_amounts(row: dict[str, Any]) -> set[int]:
    values: set[int] = set()
    budget = row.get("budget_gold") or {}
    total = safe_int(budget.get("total_krw"))
    if total:
        values.add(total)
    for item in budget.get("items") or []:
        amount = safe_int(item.get("amount_krw"))
        if amount:
            values.add(amount)
    return values


def gold_source_docs(row: dict[str, Any]) -> list[str]:
    docs = [nfc(value) for value in row.get("source_docs") or []]
    for ref in row.get("evidence_refs") or []:
        if ref.get("source_file"):
            docs.append(nfc(ref["source_file"]))
    budget = row.get("budget_gold") or {}
    for item in budget.get("items") or []:
        if item.get("source_file"):
            docs.append(nfc(item["source_file"]))
    return unique_keep_order(docs)


def row_intents(row: dict[str, Any]) -> list[str]:
    intents: list[str] = []
    task_family = str(row.get("task_family") or "")
    secondary = [str(value) for value in row.get("secondary_task_families") or []]
    text = " ".join([task_family, *secondary, str(row.get("question") or "")]).lower()

    if row.get("budget_gold") or any(term in text for term in ("budget", "예산", "금액", "사업비")):
        intents.append("budget")
    if any(term in text for term in ("기간", "마감", "deadline", "duration", "period", "일정")):
        intents.append("date_or_period")
    if any(term in text for term in ("자격", "실적", "eligibility", "qualification", "제한")):
        intents.append("qualification")
    if any(term in text for term in ("제출", "서류", "submission", "document")):
        intents.append("submission_documents")
    if task_family == "required_fields" or "required_fields" in secondary:
        intents.append("required_fields")
    return unique_keep_order(intents) or ["general"]


def load_chunks_by_source(path: Path) -> dict[str, list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    chunks = raw.get("chunks") if isinstance(raw, dict) else raw
    if not isinstance(chunks, list):
        raise ValueError(f"Unsupported chunks format: {path}")

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        source_file = metadata.get("source_file") or chunk.get("source_file")
        source_key = normalize_doc_key(source_file)
        if source_key:
            by_source[source_key].append(chunk)
    return by_source


def chunk_text(chunk: dict[str, Any]) -> str:
    return nfc(chunk.get("text") or chunk.get("content") or "")


def chunk_source_file(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return nfc(metadata.get("source_file") or chunk.get("source_file") or "")


def chunk_fact_type(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return nfc(
        chunk.get("fact_type")
        or metadata.get("fact_type")
        or metadata.get("chunk_type")
        or metadata.get("section_type")
    )


def chunk_amounts(chunk: dict[str, Any]) -> set[int]:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    values = extract_amounts(chunk_text(chunk))
    values.update(extract_amounts(metadata.get("budget")))
    values.update(extract_amounts(metadata.get("amounts")))
    values.update(extract_amounts(metadata.get("final_budget")))
    return values


def question_terms(question: str) -> list[str]:
    terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", question or "")
    stopwords = {
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
    }
    return [term for term in terms if term not in stopwords]


def score_chunk(chunk: dict[str, Any], row: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    text = chunk_text(chunk)
    fact_type = chunk_fact_type(chunk)
    intents = row_intents(row)

    amount_overlap = chunk_amounts(chunk) & gold_amounts(row)
    if amount_overlap:
        score += 100.0
        reasons.append("gold_amount_match")

    for intent in intents:
        for term in QUESTION_TYPE_TERMS.get(intent, ()):
            if term and (term in text or term in fact_type):
                score += 8.0
                reasons.append(f"{intent}_term")
                break

    q_terms = question_terms(str(row.get("question") or ""))
    if q_terms:
        overlap = sum(1 for term in q_terms if term in text or term in fact_type)
        if overlap:
            score += min(overlap, 8) * 1.5
            reasons.append(f"question_term_overlap:{overlap}")

    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    chunk_type = str(metadata.get("chunk_type") or "").lower()
    section_type = str(metadata.get("section_type") or "").lower()
    if "fact" in chunk_type:
        score += 6.0
        reasons.append("fact_candidate")
    if "table" in chunk_type:
        score += 2.0
        reasons.append("table")
    if "summary" in fact_type or "사업개요" in section_type:
        score += 1.0
        reasons.append("summary_or_overview")

    return score, unique_keep_order(reasons)


def remap_row(row: dict[str, Any], chunks_by_source: dict[str, list[dict[str, Any]]], max_refs: int) -> tuple[dict[str, Any], dict[str, Any]]:
    docs = gold_source_docs(row)
    candidates: list[tuple[float, dict[str, Any], list[str]]] = []
    for doc in docs:
        for chunk in chunks_by_source.get(normalize_doc_key(doc), []):
            score, reasons = score_chunk(chunk, row)
            if score > 0:
                candidates.append((score, chunk, reasons))

    if not candidates:
        for doc in docs:
            for chunk in chunks_by_source.get(normalize_doc_key(doc), [])[:max_refs]:
                candidates.append((0.0, chunk, ["source_doc_fallback"]))

    candidates.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id") or "")))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, chunk, reasons in candidates:
        chunk_id = str(chunk.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        selected.append(
            {
                "source_file": chunk_source_file(chunk),
                "chunk_id": chunk_id,
                "fact_type": chunk_fact_type(chunk),
                "evidence_summary": chunk_text(chunk)[:280],
                "remap_score": round(score, 3),
                "remap_reasons": reasons,
            }
        )
        if len(selected) >= max_refs:
            break

    remapped = dict(row)
    remapped["original_evidence_refs"] = row.get("evidence_refs") or []
    remapped["evidence_refs"] = [
        {
            "source_file": ref["source_file"],
            "chunk_id": ref["chunk_id"],
            "fact_type": ref["fact_type"],
            "evidence_summary": ref["evidence_summary"],
        }
        for ref in selected
    ]
    remapped["evidence_remap_note"] = "external_690_chunk_id_remap_without_modifying_eval"

    summary = {
        "id": row.get("id"),
        "task_family": row.get("task_family"),
        "question_type": row.get("question_type"),
        "source_docs": " | ".join(docs),
        "original_evidence_count": len(row.get("evidence_refs") or []),
        "remapped_evidence_count": len(selected),
        "gold_amounts": ", ".join(f"{value:,}원" for value in sorted(gold_amounts(row))),
        "top_remapped_chunk_ids": " | ".join(ref["chunk_id"] for ref in selected[:5]),
        "top_remap_reasons": " | ".join(
            ",".join(ref["remap_reasons"]) for ref in selected[:5]
        ),
    }
    return remapped, summary


def write_report(path: Path, summaries: list[dict[str, Any]], output_gold: Path) -> None:
    total = len(summaries)
    remapped = sum(1 for row in summaries if int(row["remapped_evidence_count"]) > 0)
    lines = [
        "# 690 기준 Gold Evidence Remap",
        "",
        "eval 폴더 원본은 수정하지 않고, 현재 690 chunks 기준으로 evidence_refs만 외부 파일에 재매핑한 결과입니다.",
        "",
        f"- source remapped gold: `{output_gold}`",
        f"- total questions: {total}",
        f"- questions with remapped evidence: {remapped}",
        "",
        "## 확인 포인트",
        "",
        "- 원본 `evidence_refs.chunk_id`는 eval 폴더에 그대로 둡니다.",
        "- 참고용 evidence recall은 이 외부 remapped gold 파일을 `--gold`로 넘겨서 계산합니다.",
        "- budget 문항은 gold amount가 실제 포함된 현재 690 chunk를 최우선으로 매핑했습니다.",
        "- budget 외 문항은 질문 유형 키워드, 질문 단어 overlap, fact/table chunk 여부를 기준으로 현재 문서 내 chunk를 골랐습니다.",
        "",
        "## Samples",
        "",
        "| id | task_family | original | remapped | gold_amounts | top chunks |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in summaries[:20]:
        lines.append(
            f"| {row['id']} | {row['task_family']} | {row['original_evidence_count']} | "
            f"{row['remapped_evidence_count']} | {row['gold_amounts'] or '-'} | {row['top_remapped_chunk_ids']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    gold_rows = read_jsonl(args.gold)
    chunks_by_source = load_chunks_by_source(args.chunks)

    remapped_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for row in gold_rows:
        remapped, summary = remap_row(row, chunks_by_source, args.max_refs)
        remapped_rows.append(remapped)
        summaries.append(summary)

    output_gold = args.output_dir / "rfp_domain_gold_sample_690_remapped.jsonl"
    output_summary = args.output_dir / "rfp_domain_gold_sample_690_remap_summary.csv"
    output_report = args.output_dir / "rfp_domain_gold_sample_690_remap_summary.md"
    write_jsonl(output_gold, remapped_rows)
    write_csv(output_summary, summaries)
    write_report(output_report, summaries, output_gold)
    print(f"wrote remapped gold to {output_gold}")
    print(f"wrote summary to {output_report}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an external evidence_refs remap for current chunks without editing eval files."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-refs", type=int, default=8)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
