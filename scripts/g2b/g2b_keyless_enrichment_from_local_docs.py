#!/usr/bin/env python3
"""Keyless G2B/RFP enrichment for 690 RFP documents.

This script does not call the public-data API. It combines:
1) local g2b_master_cleaned.csv for notice number / bid deadline,
2) local HWPX/PDF source text for strongly labelled amount/date evidence,
3) conservative confidence labels so uncertain values are not treated as final.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    import olefile
except Exception:  # pragma: no cover
    olefile = None

OUTPUT_COLUMNS = [
    "source_file",
    "normalized_project_name",
    "issuer",
    "source_doc_path",
    "source_doc_format",
    "bid_notice_no",
    "bid_notice_ord",
    "notice_year",
    "g2b_title",
    "bid_deadline",
    "bid_submission_start_at",
    "bid_submission_end_at",
    "g2b_allocated_budget",
    "g2b_estimated_price",
    "g2b_vat",
    "g2b_other_amount",
    "rfp_project_budget",
    "rfp_estimated_price",
    "rfp_vat",
    "rfp_base_amount",
    "rfp_other_amount",
    "rfp_bid_deadline",
    "rfp_submission_start_at",
    "rfp_submission_end_at",
    "final_project_budget",
    "final_bid_deadline",
    "amount_source_origin",
    "deadline_source_origin",
    "match_status",
    "match_score",
    "extraction_confidence",
    "needs_manual_review_reason",
    "amount_evidence_label",
    "amount_evidence_snippet",
    "deadline_evidence_label",
    "deadline_evidence_snippet",
    "raw_master_json",
    "fetched_at",
]

DATE_PATTERN = re.compile(
    r"(20\d{2})\s*[./년-]\s*(\d{1,2})\s*[./월-]\s*(\d{1,2})\s*(?:일)?\s*(?:\([^)]*\))?\s*(?:[\s,]*(\d{1,2})\s*[:시]\s*(\d{2})?)?"
)
AMOUNT_PATTERN = re.compile(
    r"(?<![\d.])([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)\s*(억\s*원|억원|백만\s*원|백만원|천\s*원|천원|원)"
)

AMOUNT_LABELS = {
    "rfp_project_budget": [
        "사업금액", "사업 금액", "사업예산", "사업 예산", "총사업비", "총 사업비", "소요예산", "소요 예산",
        "예산금액", "예산 금액", "배정예산", "배정 예산", "기간/예산", "기간 및 예산", "예산/기간",
    ],
    "rfp_estimated_price": ["추정가격", "추정 가격", "예정가격", "예정 가격"],
    "rfp_vat": ["부가가치세", "부가 가치세", "VAT", "vat"],
    "rfp_base_amount": ["기초금액", "기초 금액"],
    "rfp_other_amount": ["기타금액", "기타 금액"],
}

DATE_LABELS = {
    "rfp_bid_deadline": [
        "입찰마감일시", "입찰 마감일시", "입찰서접수 마감일시", "입찰서 접수 마감일시", "입찰서 제출마감",
        "전자입찰서 제출마감", "가격입찰서 제출마감", "가격입찰 마감", "입찰등록 마감", "투찰 마감",
    ],
    "rfp_submission_start_at": [
        "입찰서접수 개시일시", "입찰서 접수 개시일시", "전자입찰서 제출개시", "가격입찰서 제출개시", "입찰개시일시",
    ],
    "rfp_submission_end_at": [
        "입찰서접수 마감일시", "입찰서 접수 마감일시", "전자입찰서 제출마감", "가격입찰서 제출마감", "입찰마감일시",
    ],
}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def normalize_doc_name(value: Any) -> str:
    text = normalize_text(Path(str(value or "")).name)
    return re.sub(r"\.(hwp|hwpx|pdf|json|jsonl)$", "", text, flags=re.I).strip()


def compact_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", normalize_doc_name(value)).lower()


def first(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() and str(value).strip().lower() != "nan":
            return str(value).strip()
    return ""


def split_notice_ord(notice_no: str) -> str:
    if "-" in notice_no:
        return notice_no.rsplit("-", 1)[1]
    return ""


def parse_master_deadline(value: str) -> str:
    text = normalize_text(value)
    m = re.search(r"\(([^)]*)\)", text)
    if m:
        value = m.group(1).strip()
        if value and value != "-":
            return normalize_datetime(value)
    return ""


def normalize_datetime(value: str) -> str:
    text = normalize_text(value)
    m = DATE_PATTERN.search(text)
    if not m:
        return ""
    year, month, day, hour, minute = m.groups()
    hour = hour or "00"
    minute = minute or "00"
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}"


def parse_amount_to_krw(number: str, unit: str) -> int | None:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    unit = re.sub(r"\s+", "", unit)
    if unit in {"원"}:
        multiplier = 1
    elif unit in {"천원"}:
        multiplier = 1_000
    elif unit in {"백만원"}:
        multiplier = 1_000_000
    elif unit in {"억원"}:
        multiplier = 100_000_000
    else:
        return None
    return int(round(value * multiplier))


def format_krw(value: int | None) -> str:
    return f"{value:,}원" if value is not None else ""


@dataclass
class ExtractedValue:
    value: str = ""
    value_krw: int | None = None
    label: str = ""
    snippet: str = ""
    confidence: str = ""


def clean_snippet(text: str, start: int, end: int, radius: int = 90) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return normalize_text(text[left:right])[:500]


def extract_amount(text: str, labels: list[str]) -> ExtractedValue:
    if not text:
        return ExtractedValue(confidence="missing")
    best: ExtractedValue | None = None
    for label in labels:
        for lm in re.finditer(re.escape(label), text, flags=re.I):
            window = text[lm.end(): lm.end() + 220]
            am = AMOUNT_PATTERN.search(window)
            if not am:
                continue
            value_krw = parse_amount_to_krw(am.group(1), am.group(2))
            if value_krw is None:
                continue
            # Avoid obvious tiny placeholders as project budget final values.
            confidence = "high"
            if value_krw <= 10_000 and label not in {"부가가치세", "VAT", "vat"}:
                confidence = "low_small_amount"
            start = lm.start()
            end = lm.end() + am.end()
            snippet = clean_snippet(text, start, end)
            if is_excluded_project_budget_context(label, snippet):
                continue
            candidate = ExtractedValue(format_krw(value_krw), value_krw, label, snippet, confidence)
            if best is None:
                best = candidate
            elif confidence == "high" and (best.confidence != "high" or value_krw > (best.value_krw or 0)):
                best = candidate
    return best or ExtractedValue(confidence="missing")


def is_excluded_project_budget_context(label: str, snippet: str) -> bool:
    if label not in {"사업금액", "사업 금액", "총사업비", "총 사업비", "사업예산", "사업 예산", "소요예산", "소요 예산", "예산금액", "예산 금액", "배정예산", "배정 예산", "기간/예산", "기간 및 예산", "예산/기간"}:
        return False
    text = normalize_text(snippet)
    # These phrases usually describe software-company participation thresholds, not this RFP's budget.
    exclusion_patterns = [
        r"사업금액.{0,20}하한",
        r"사업\s*금액.{0,20}하한",
        r"총사업금액.{0,30}미만",
        r"사업금액이.{0,30}미만",
        r"사업\s*금액이.{0,30}미만",
        r"대기업.{0,80}참여",
        r"중견기업.{0,80}참여",
        r"소프트웨어사업자.{0,80}참여",
        r"입찰참여\s*제한금액",
        r"사업\s*참여\s*지원",
    ]
    return any(re.search(pattern, text) for pattern in exclusion_patterns)


def extract_date(text: str, labels: list[str]) -> ExtractedValue:
    if not text:
        return ExtractedValue(confidence="missing")
    for label in labels:
        for lm in re.finditer(re.escape(label), text, flags=re.I):
            window = text[lm.end(): lm.end() + 260]
            dm = DATE_PATTERN.search(window)
            if dm:
                dt = normalize_datetime(dm.group(0))
                if dt:
                    start = lm.start()
                    end = lm.end() + dm.end()
                    return ExtractedValue(dt, None, label, clean_snippet(text, start, end), "medium")
    return ExtractedValue(confidence="missing")


def extract_hwpx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            if "Preview/PrvText.txt" in z.namelist():
                return z.read("Preview/PrvText.txt").decode("utf-8", errors="ignore")
            parts = []
            for name in sorted(n for n in z.namelist() if n.startswith("Contents/") and n.endswith(".xml")):
                raw = z.read(name).decode("utf-8", errors="ignore")
                raw = re.sub(r"<[^>]+>", " ", raw)
                parts.append(raw)
            return "\n".join(parts)
    except Exception:
        return ""


def extract_pdf_text(path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def extract_hwp_text(path: Path) -> str:
    """Extract plain text from HWP 5 BodyText streams without external API calls."""
    if olefile is None:
        return ""
    try:
        with olefile.OleFileIO(str(path)) as ole:
            if not ole.exists("FileHeader"):
                return ""
            header = ole.openstream("FileHeader").read()
            compressed = len(header) >= 40 and bool(int.from_bytes(header[36:40], "little") & 1)
            parts = []
            for entry in ole.listdir():
                name = "/".join(entry)
                if not name.startswith("BodyText/Section"):
                    continue
                data = ole.openstream(name).read()
                if compressed:
                    try:
                        data = zlib.decompress(data, -15)
                    except Exception:
                        continue
                pos = 0
                while pos + 4 <= len(data):
                    record_header = int.from_bytes(data[pos:pos + 4], "little")
                    pos += 4
                    tag_id = record_header & 0x3FF
                    size = (record_header >> 20) & 0xFFF
                    if size == 0xFFF:
                        if pos + 4 > len(data):
                            break
                        size = int.from_bytes(data[pos:pos + 4], "little")
                        pos += 4
                    payload = data[pos:pos + size]
                    pos += size
                    if tag_id == 67:  # HWPTAG_PARA_TEXT
                        text = payload.decode("utf-16le", errors="ignore")
                        if text:
                            parts.append(text)
            text = "\n".join(parts)
            return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    except Exception:
        return ""


def build_source_maps(project_root: Path) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    hwpx_map = {}
    for path in (project_root / "data/hwpx_664").glob("*.hwpx"):
        hwpx_map[compact_key(path.name)] = path
    original_map = {}
    for path in (project_root / "data/original_data_list").glob("*"):
        if path.is_file():
            original_map[compact_key(path.name)] = path
    pdf_map = {k: p for k, p in original_map.items() if p.suffix.lower() == ".pdf"}
    return hwpx_map, original_map, pdf_map


def match_master(src: dict[str, Any], master_rows: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    source_file = first(src, ["source_file", "FileName", "filename", "file_name"])
    project = first(src, ["normalized_project_name", "project_name", "사업명", "norm_name"]) or normalize_doc_name(source_file)
    issuer = first(src, ["issuer", "발주기관", "공고기관"])
    project_tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", normalize_text(project).lower()))
    source_key = compact_key(source_file)
    project_key = compact_key(project)
    best_score = 0.0
    best: dict[str, Any] = {}
    for item in master_rows:
        title = first(item, ["공고명", "g2b_title", "bidNtceNm"])
        agency = first(item, ["공고기관", "수요기관", "issuer"])
        title_key = compact_key(title)
        score = 0.0
        if title_key:
            if project_key and project_key == title_key:
                score = 1.0
            elif source_key and source_key == title_key:
                score = 1.0
            elif project_key and (project_key in title_key or title_key in project_key):
                score = 0.92
            else:
                title_tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", normalize_text(title).lower()))
                inter = len(project_tokens & title_tokens)
                union = len(project_tokens | title_tokens) or 1
                score = min(0.84, inter / union + min(inter, 5) * 0.055)
        if issuer and agency:
            ni = normalize_text(issuer)
            na = normalize_text(agency)
            if ni and (ni in na or na in ni):
                score += 0.08
        rank_score = score
        # Prefer same year-ish titles over weak token overlap.
        if rank_score > best_score:
            best_score = rank_score
            best = item
    return round(min(best_score, 1.0), 4), best if best_score >= 0.86 else {}


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--input", default="data/g2b_notice_input_690.csv")
    parser.add_argument("--g2b-master", default="data/g2b_master_cleaned.csv")
    parser.add_argument("--output", default="data/g2b_notice_enrichment_690_keyless.csv")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_path = (project_root / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    master_path = (project_root / args.g2b_master).resolve() if not Path(args.g2b_master).is_absolute() else Path(args.g2b_master)
    output_path = (project_root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = load_rows(input_path)
    if args.limit:
        rows = rows[: args.limit]
    master_rows = pd.read_csv(master_path).fillna("").to_dict("records") if master_path.exists() else []
    hwpx_map, original_map, pdf_map = build_source_maps(project_root)

    out_rows: list[dict[str, Any]] = []
    cache: dict[Path, str] = {}
    for idx, src in enumerate(rows, start=1):
        source_file = first(src, ["source_file"])
        project = first(src, ["normalized_project_name"]) or normalize_doc_name(source_file)
        issuer = first(src, ["issuer"])
        key = compact_key(source_file)
        src_path = hwpx_map.get(key) or original_map.get(key)
        source_format = src_path.suffix.lower().lstrip(".") if src_path else "missing"
        text = ""
        if src_path:
            if src_path in cache:
                text = cache[src_path]
            elif src_path.suffix.lower() == ".hwpx":
                text = extract_hwpx_text(src_path)
                cache[src_path] = text
            elif src_path.suffix.lower() == ".pdf":
                text = extract_pdf_text(src_path)
                cache[src_path] = text
            elif src_path.suffix.lower() == ".hwp":
                text = extract_hwp_text(src_path)
                cache[src_path] = text
            else:
                text = ""

        match_score, master = match_master(src, master_rows)
        notice_no = first(master, ["입찰공고번호", "bid_notice_no"])
        master_deadline = parse_master_deadline(first(master, ["게시일시(입찰마감일시)", "입찰마감일시", "g2b_bid_deadline"]))
        notice_year = ""
        ym = re.search(r"(20\d{2})", " ".join([notice_no, master_deadline, first(master, ["공고명"])]))
        if ym:
            notice_year = ym.group(1)

        extracted_amounts = {field: extract_amount(text, labels) for field, labels in AMOUNT_LABELS.items()}
        extracted_dates = {field: extract_date(text, labels) for field, labels in DATE_LABELS.items()}

        project_budget = extracted_amounts["rfp_project_budget"]
        final_project_budget = ""
        amount_origin = ""
        confidence_parts = []
        review_reasons = []
        if project_budget.value and project_budget.confidence == "high":
            final_project_budget = project_budget.value
            amount_origin = "rfp_body_strong_label"
            confidence_parts.append("amount_high")
        elif project_budget.value:
            review_reasons.append(f"project_budget_{project_budget.confidence}")
            confidence_parts.append("amount_low")
        else:
            review_reasons.append("project_budget_not_found_in_local_source")
            confidence_parts.append("amount_missing")

        final_deadline = master_deadline or extracted_dates["rfp_bid_deadline"].value
        deadline_origin = "g2b_master" if master_deadline else ("rfp_body_label" if final_deadline else "")
        if final_deadline:
            confidence_parts.append("deadline_present")
        else:
            review_reasons.append("bid_deadline_not_found")
            confidence_parts.append("deadline_missing")

        if not src_path:
            review_reasons.append("source_file_not_found")
        elif not text:
            review_reasons.append(f"text_extraction_failed_{source_format}")

        match_status = "matched_master_and_local_text" if master and text else ""
        if master and not text:
            match_status = "matched_master_text_missing"
        elif not master and text:
            match_status = "local_text_only_needs_notice_match"
        elif not master and not text:
            match_status = "needs_manual_review"

        best_amount_ev = next((ev for ev in [project_budget, extracted_amounts["rfp_estimated_price"], extracted_amounts["rfp_base_amount"]] if ev.value), ExtractedValue(confidence="missing"))
        best_deadline_ev = next((ev for ev in [extracted_dates["rfp_bid_deadline"], extracted_dates["rfp_submission_end_at"], extracted_dates["rfp_submission_start_at"]] if ev.value), ExtractedValue(confidence="missing"))

        out_rows.append({
            "source_file": source_file,
            "normalized_project_name": project,
            "issuer": issuer,
            "source_doc_path": str(src_path.relative_to(project_root)) if src_path else "",
            "source_doc_format": source_format,
            "bid_notice_no": notice_no,
            "bid_notice_ord": split_notice_ord(notice_no),
            "notice_year": notice_year,
            "g2b_title": first(master, ["공고명"]),
            "bid_deadline": master_deadline,
            "bid_submission_start_at": extracted_dates["rfp_submission_start_at"].value,
            "bid_submission_end_at": extracted_dates["rfp_submission_end_at"].value or master_deadline,
            "g2b_allocated_budget": "",
            "g2b_estimated_price": "",
            "g2b_vat": "",
            "g2b_other_amount": "",
            "rfp_project_budget": project_budget.value if project_budget.confidence == "high" else "",
            "rfp_estimated_price": extracted_amounts["rfp_estimated_price"].value,
            "rfp_vat": extracted_amounts["rfp_vat"].value,
            "rfp_base_amount": extracted_amounts["rfp_base_amount"].value,
            "rfp_other_amount": extracted_amounts["rfp_other_amount"].value,
            "rfp_bid_deadline": extracted_dates["rfp_bid_deadline"].value,
            "rfp_submission_start_at": extracted_dates["rfp_submission_start_at"].value,
            "rfp_submission_end_at": extracted_dates["rfp_submission_end_at"].value,
            "final_project_budget": final_project_budget,
            "final_bid_deadline": final_deadline,
            "amount_source_origin": amount_origin,
            "deadline_source_origin": deadline_origin,
            "match_status": match_status,
            "match_score": match_score,
            "extraction_confidence": ";".join(confidence_parts),
            "needs_manual_review_reason": ";".join(dict.fromkeys(review_reasons)),
            "amount_evidence_label": best_amount_ev.label,
            "amount_evidence_snippet": best_amount_ev.snippet,
            "deadline_evidence_label": best_deadline_ev.label,
            "deadline_evidence_snippet": best_deadline_ev.snippet,
            "raw_master_json": json.dumps(master, ensure_ascii=False) if master else "",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        if idx % 50 == 0 or idx == len(rows):
            print(f"processed {idx}/{len(rows)}")

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    summary = {
        "row_count": len(out_rows),
        "notice_no_count": sum(1 for r in out_rows if r["bid_notice_no"]),
        "master_deadline_count": sum(1 for r in out_rows if r["bid_deadline"]),
        "rfp_project_budget_count": sum(1 for r in out_rows if r["rfp_project_budget"]),
        "final_project_budget_count": sum(1 for r in out_rows if r["final_project_budget"]),
        "final_bid_deadline_count": sum(1 for r in out_rows if r["final_bid_deadline"]),
        "source_format_counts": {},
        "match_status_counts": {},
    }
    for r in out_rows:
        summary["source_format_counts"][r["source_doc_format"]] = summary["source_format_counts"].get(r["source_doc_format"], 0) + 1
        summary["match_status_counts"][r["match_status"]] = summary["match_status_counts"].get(r["match_status"], 0) + 1
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"saved: {output_path}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
