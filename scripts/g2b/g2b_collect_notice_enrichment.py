#!/usr/bin/env python3
"""Collect G2B/Nara notice enrichment data for RFP corpus documents.

The script intentionally stores G2B notice values separately from RFP body values.
It does not infer missing amounts. If an amount is not returned by the API, the
row is left blank and marked for manual review.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

API_BASE = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
SERVICE_OPERATIONS = [
    "getBidPblancListInfoServcPPSSrch",
    "getBidPblancListInfoServc",
]
OUTPUT_COLUMNS = [
    "source_file",
    "normalized_project_name",
    "issuer",
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
    "g2b_is_cancelled",
    "g2b_notice_kind",
    "match_status",
    "match_score",
    "raw_response_json",
    "fetched_at",
]

FIELD_ALIASES = {
    "bid_notice_no": ["bidNtceNo", "bidPblancNo", "ntceNo", "공고번호", "입찰공고번호"],
    "bid_notice_ord": ["bidNtceOrd", "bidPblancOrd", "ntceOrd", "공고차수"],
    "g2b_title": ["bidNtceNm", "bidPblancNm", "ntceNm", "공고명"],
    "bid_deadline": ["bidClseDt", "bidClseDate", "bidClseTm", "입찰마감일시"],
    "bid_submission_start_at": ["bidBeginDt", "bidDcPeBeginDt", "bidNtceBgnDt", "입찰서접수개시일시"],
    "bid_submission_end_at": ["bidClseDt", "bidDcPeEndDt", "bidNtceEndDt", "입찰서접수마감일시"],
    "g2b_allocated_budget": ["asignBdgtAmt", "alotBgtAmt", "bdgtAmt", "배정예산"],
    "g2b_estimated_price": ["presmptPrce", "estimatedPrice", "추정가격"],
    "g2b_vat": ["VAT", "vat", "vatAmt", "부가가치세"],
    "g2b_other_amount": ["etcAmt", "etcAmount", "otherAmt", "기타금액"],
    "g2b_is_cancelled": ["cancYn", "cancelYn", "isCancelled", "취소여부"],
    "g2b_notice_kind": ["ntceKindNm", "bidNtceSttusNm", "공고종류", "구분"],
}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_doc_name(value: Any) -> str:
    text = normalize_text(Path(str(value or "")).name)
    while re.search(r"\.(hwp|hwpx|pdf|json|jsonl)$", text, flags=re.I):
        text = re.sub(r"\.(hwp|hwpx|pdf|json|jsonl)$", "", text, flags=re.I).strip()
    return text


def compact_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", normalize_doc_name(value)).lower()


def get_api_key() -> str:
    key = os.getenv("NARA_API_KEY") or os.getenv("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise SystemExit(
            "Nara/G2B API key is missing. Set NARA_API_KEY or DATA_GO_KR_SERVICE_KEY.\n"
            "Example: export NARA_API_KEY='...service key...'"
        )
    return key


def read_input_rows(input_path: Path) -> list[dict[str, Any]]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if pd is None:
            raise RuntimeError("pandas/openpyxl is required for Excel input")
        return pd.read_excel(input_path).fillna("").to_dict("records")
    if suffix == ".csv":
        with input_path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix in {".jsonl", ".json"}:
        rows = []
        with input_path.open(encoding="utf-8") as f:
            if suffix == ".json":
                data = json.load(f)
                return data if isinstance(data, list) else data.get("rows", [])
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
    raise ValueError(f"Unsupported input file: {input_path}")


def load_g2b_master(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    if pd is not None:
        return pd.read_csv(path).fillna("").to_dict("records")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def first_value(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def extract_notice_from_master(row: dict[str, Any], master_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_file = first_value(row, ["source_file", "FileName", "filename", "file_name"])
    project_name = first_value(row, ["project_name", "사업명", "normalized_project_name", "norm_name", "doc_key"])
    issuer = first_value(row, ["issuer", "발주기관", "공고기관"])
    key_candidates = [compact_key(source_file), compact_key(project_name)]
    best: tuple[float, dict[str, Any]] = (0.0, {})
    for item in master_rows:
        title = first_value(item, ["공고명", "g2b_title", "bidNtceNm"])
        agency = first_value(item, ["공고기관", "수요기관", "issuer"])
        title_key = compact_key(title)
        score = 0.0
        for key in key_candidates:
            if not key or not title_key:
                continue
            if key == title_key:
                score = max(score, 1.0)
            elif key in title_key or title_key in key:
                score = max(score, 0.92)
            else:
                overlap = len(set(re.findall(r"[가-힣A-Za-z0-9]+", normalize_text(project_name))) & set(re.findall(r"[가-힣A-Za-z0-9]+", normalize_text(title))))
                score = max(score, min(0.75, overlap / 6.0))
        if issuer and agency and normalize_text(issuer) in normalize_text(agency):
            score += 0.08
        if score > best[0]:
            best = (score, item)
    if best[0] >= 0.88:
        return {"match_score": round(best[0], 4), **best[1]}
    return {}


def fetch_json(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_text": body}


def normalize_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", {}).get("body", {}) if isinstance(payload, dict) else {}
    items = body.get("items", {})
    if isinstance(items, dict):
        item = items.get("item", [])
    else:
        item = items
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return [x for x in item if isinstance(x, dict)]
    return []


def query_g2b(api_key: str, *, notice_no: str = "", title: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors = []
    for op in SERVICE_OPERATIONS:
        params = {
            "serviceKey": api_key,
            "ServiceKey": api_key,
            "pageNo": "1",
            "numOfRows": "10",
            "type": "json",
        }
        if notice_no:
            params["bidNtceNo"] = notice_no.split("-")[0]
        elif title:
            params["bidNtceNm"] = title[:80]
        url = f"{API_BASE}/{op}?{urlencode(params)}"
        try:
            payload = fetch_json(url)
            items = normalize_items(payload)
            if items:
                return items, {"operation": op, "url": url, "payload": payload}
            errors.append({"operation": op, "payload": payload})
        except Exception as exc:  # pragma: no cover - network dependent
            errors.append({"operation": op, "error": type(exc).__name__, "message": str(exc)})
    return [], {"errors": errors}


def pick(item: dict[str, Any], canonical: str) -> str:
    return first_value(item, FIELD_ALIASES.get(canonical, []))


def amount_status(row: dict[str, str]) -> str:
    amount_values = [row.get("g2b_allocated_budget"), row.get("g2b_estimated_price"), row.get("g2b_vat"), row.get("g2b_other_amount")]
    if any(str(v or "").strip() for v in amount_values):
        return "matched_with_amount"
    return "amount_missing_in_g2b"


def build_output_row(src: dict[str, Any], item: dict[str, Any], raw: dict[str, Any], master_match: dict[str, Any], status_prefix: str) -> dict[str, Any]:
    source_file = first_value(src, ["source_file", "FileName", "filename", "file_name"])
    normalized_project_name = first_value(src, ["normalized_project_name", "project_name", "사업명", "norm_name", "doc_key"]) or normalize_doc_name(source_file)
    issuer = first_value(src, ["issuer", "발주기관", "공고기관"])
    notice_no = pick(item, "bid_notice_no") or first_value(master_match, ["입찰공고번호", "bid_notice_no"])
    deadline = pick(item, "bid_deadline") or first_value(master_match, ["입찰마감일시", "g2b_bid_deadline"])
    title = pick(item, "g2b_title") or first_value(master_match, ["공고명", "g2b_title"])
    notice_year = ""
    year_match = re.search(r"(20\d{2})", " ".join([notice_no, deadline, title]))
    if year_match:
        notice_year = year_match.group(1)
    row = {
        "source_file": source_file,
        "normalized_project_name": normalized_project_name,
        "issuer": issuer,
        "bid_notice_no": notice_no,
        "bid_notice_ord": pick(item, "bid_notice_ord"),
        "notice_year": notice_year,
        "g2b_title": title,
        "bid_deadline": deadline,
        "bid_submission_start_at": pick(item, "bid_submission_start_at"),
        "bid_submission_end_at": pick(item, "bid_submission_end_at"),
        "g2b_allocated_budget": pick(item, "g2b_allocated_budget"),
        "g2b_estimated_price": pick(item, "g2b_estimated_price"),
        "g2b_vat": pick(item, "g2b_vat"),
        "g2b_other_amount": pick(item, "g2b_other_amount"),
        "g2b_is_cancelled": pick(item, "g2b_is_cancelled"),
        "g2b_notice_kind": pick(item, "g2b_notice_kind") or first_value(master_match, ["구분"]),
        "match_status": status_prefix,
        "match_score": first_value(master_match, ["match_score"]),
        "raw_response_json": json.dumps(raw, ensure_ascii=False)[:30000],
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if status_prefix.startswith("matched"):
        row["match_status"] = amount_status(row)
    return row


def find_default_input(project_root: Path) -> Path:
    candidates = [
        project_root / "outputs/parsing_p4_hwpx_690/metadata_light_690.xlsx",
        project_root / "outputs/parsing_p4_hwpx_690/metadata_light_690.csv",
        project_root / "outputs/parsing_p4_hwpx_690/pilot_docs_690.csv",
        project_root / "outputs/parsing_p4_hwpx_125_datafix_goalfix/metadata_light_125.xlsx",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("No default metadata file found. Pass --input explicitly.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="data/g2b_notice_enrichment_690.csv")
    parser.add_argument("--g2b-master", default="data/g2b_master_cleaned.csv")
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_path = Path(args.input).resolve() if args.input else find_default_input(project_root)
    output_path = (project_root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master_path = (project_root / args.g2b_master).resolve() if args.g2b_master else None

    api_key = get_api_key()
    src_rows = read_input_rows(input_path)
    if args.limit:
        src_rows = src_rows[: args.limit]
    master_rows = load_g2b_master(master_path)

    output_rows = []
    for idx, src in enumerate(src_rows, start=1):
        source_file = first_value(src, ["source_file", "FileName", "filename", "file_name"])
        title = first_value(src, ["project_name", "normalized_project_name", "사업명", "norm_name", "doc_key"]) or normalize_doc_name(source_file)
        master_match = extract_notice_from_master(src, master_rows)
        notice_no = first_value(src, ["bid_notice_no", "g2b_notice_id", "final_notice_id", "입찰공고번호"]) or first_value(master_match, ["입찰공고번호", "g2b_notice_id"])
        items, raw = query_g2b(api_key, notice_no=notice_no, title=title)
        if items:
            item = items[0]
            status = "matched_api"
        elif master_match:
            item = {}
            raw = {"api_result": raw, "master_match_only": master_match}
            status = "matched_master_only_needs_api_detail"
        else:
            item = {}
            status = "needs_manual_review"
        output_rows.append(build_output_row(src, item, raw, master_match, status))
        print(f"{idx}/{len(src_rows)} {status}: {source_file}")
        if args.sleep:
            time.sleep(args.sleep)

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
