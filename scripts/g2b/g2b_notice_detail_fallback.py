#!/usr/bin/env python3
"""Fill missing 690 enrichment fields from G2B public detail endpoints without API keys.

Policy:
- RFP/local extraction remains primary evidence.
- G2B detail is used only when final_project_budget / final_bid_deadline is missing.
- bid_notice_no can only be filled when an existing master/list match already has a notice number.
- If G2B detail does not return a notice, leave values empty and mark the reason.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.g2b.go.kr",
    "Referer": "https://www.g2b.go.kr/",
}
COUNT_URL = "https://www.g2b.go.kr/pn/pnp/pnpe/commBidPbac/selectBidPbacNoCnt.do"
ITEM_DETAIL_URL = "https://www.g2b.go.kr/pn/pnp/pnpe/ItemBidPbac/selectItemAnncMngV.do"
TECH_DETAIL_URL = "https://www.g2b.go.kr/pn/pnp/pnpe/TechBidPbac/selectTechAnncMngV.do"


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def split_notice(value: str) -> tuple[str, str]:
    text = clean(value)
    if not text:
        return "", ""
    if "-" in text:
        no, ord_ = text.rsplit("-", 1)
        return no.strip(), ord_.strip().zfill(3 if len(ord_.strip()) >= 3 else 2)
    return text, ""


def normalize_ord(no: str, ord_: str) -> str:
    ord_ = clean(ord_)
    if not ord_:
        _, from_no = split_notice(no)
        ord_ = from_no
    if not ord_:
        return ""
    # B-series K-water notices use 2 digits; standard G2B/R25 notices generally use 3.
    if clean(no).startswith("B"):
        return ord_.zfill(2)
    return ord_.zfill(3)


def normalize_datetime(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    m = re.search(r"(20\d{2})[-/.년]\s*(\d{1,2})[-/.월]\s*(\d{1,2})\s*(?:일)?\s*(\d{1,2})?\s*[:시]?\s*(\d{2})?", text)
    if not m:
        return text
    y, mo, d, h, mi = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(h or '0'):02d}:{int(mi or '0'):02d}"


def int_amount(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    text = re.sub(r"[^0-9.-]", "", text)
    if not text or text in {"-", "."}:
        return None
    try:
        amount = int(round(float(text)))
    except ValueError:
        return None
    if amount <= 10_000:
        return None
    return amount


def krw(value: int | None) -> str:
    return f"{value:,}원" if value is not None else ""


def post_json(session: requests.Session, url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    resp = session.post(url, headers=HEADERS, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_count(session: requests.Session, no: str, ord_: str) -> dict[str, Any]:
    return post_json(session, COUNT_URL, {"dmParam": {"bidPbancNo": no, "bidPbancOrd": ord_}}).get("result") or {}


def get_detail(session: requests.Session, no: str, ord_: str, count: dict[str, Any]) -> dict[str, Any]:
    prcm = clean(count.get("prcmBsneSeCd"))
    scsbd = clean(count.get("scsbdMthdCd"))
    endpoint = TECH_DETAIL_URL if prcm == "05" else ITEM_DETAIL_URL
    payload = {"dmItemMap": {"bidPbancNo": no, "bidPbancOrd": ord_, "prcmBsneSeCd": prcm, "scsbdMthdCd": scsbd}}
    detail = post_json(session, endpoint, payload)
    dm = detail.get("dmItemMap") or {}
    if not isinstance(dm, dict):
        dm = {}
    dm["_detail_endpoint"] = endpoint
    dm["_prcmBsneSeCd"] = prcm
    dm["_scsbdMthdCd"] = scsbd
    return dm


def pick_budget(dm: dict[str, Any]) -> tuple[str, str, str, str, str]:
    allocated = int_amount(dm.get("alotBgtAmt")) or int_amount(dm.get("bizAmt")) or int_amount(dm.get("bgtAmt"))
    estimated = int_amount(dm.get("prspPrce")) or int_amount(dm.get("bidPrspPrce"))
    vat = int_amount(dm.get("vatAmt"))
    other = int_amount(dm.get("etcAmt")) or int_amount(dm.get("bidEtcAmt"))
    # final project budget should prefer allocated/biz/budget amount. Estimated price is stored separately.
    final = allocated
    return krw(final), krw(allocated), krw(estimated), krw(vat), krw(other)


def detail_snippet(dm: dict[str, Any]) -> str:
    keys = [
        "bidPbancNo", "bidPbancOrd", "bidPbancNm", "pbancInstUntyGrpNm", "dmstUntyGrpNm",
        "alotBgtAmt", "bizAmt", "bgtAmt", "prspPrce", "vatAmt", "etcAmt",
        "slprRcptBgngDt", "slprRcptDdlnDt", "onbsPrnmntDt",
    ]
    parts = []
    for key in keys:
        value = clean(dm.get(key))
        if value:
            parts.append(f"{key}={value}")
    return " | ".join(parts)[:1000]


def append_reason(existing: str, reason: str) -> str:
    parts = [p for p in clean(existing).split(";") if p]
    if reason and reason not in parts:
        parts.append(reason)
    return ";".join(parts)


def remove_reason(existing: str, remove_prefixes: tuple[str, ...]) -> str:
    parts = []
    for part in [p for p in clean(existing).split(";") if p]:
        if any(part.startswith(prefix) for prefix in remove_prefixes):
            continue
        parts.append(part)
    return ";".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--input", default="data/g2b_notice_enrichment_690_keyless.csv")
    ap.add_argument("--output", default="data/g2b_notice_enrichment_690_keyless_detail_filled.csv")
    ap.add_argument("--failed-output", default="data/g2b_notice_detail_fallback_failed.csv")
    ap.add_argument("--cache", default="data/g2b_notice_detail_fallback_cache.jsonl")
    ap.add_argument("--sleep", type=float, default=0.05)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    root = Path(args.project_root)
    input_path = root / args.input
    output_path = root / args.output
    failed_path = root / args.failed_output
    cache_path = root / args.cache
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_path, dtype=str).fillna("")
    rows = df.to_dict("records")
    if args.limit:
        rows = rows[: args.limit]

    cache: dict[str, dict[str, Any]] = {}
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    cache[item["cache_key"]] = item

    session = requests.Session()
    out_rows = []
    failed = []
    stats = {
        "rows": 0,
        "detail_attempted": 0,
        "detail_success": 0,
        "budget_filled": 0,
        "deadline_filled": 0,
        "g2b_budget_columns_filled": 0,
        "count_not_found": 0,
        "notice_missing_cannot_detail": 0,
        "errors": 0,
    }

    for idx, row in enumerate(rows, start=1):
        stats["rows"] += 1
        bid_notice = clean(row.get("bid_notice_no"))
        no, ord_from_no = split_notice(bid_notice)
        ord_ = normalize_ord(no, clean(row.get("bid_notice_ord")) or ord_from_no)
        needs_budget = clean(row.get("final_project_budget")) == ""
        needs_deadline = clean(row.get("final_bid_deadline")) == ""
        needs_related_amounts = not all(clean(row.get(k)) for k in ["g2b_allocated_budget", "g2b_estimated_price"])

        if not bid_notice:
            if needs_budget or needs_deadline:
                stats["notice_missing_cannot_detail"] += 1
                row["needs_manual_review_reason"] = append_reason(row.get("needs_manual_review_reason", ""), "g2b_detail_skipped_notice_no_missing")
                failed.append({**row, "fallback_status": "notice_no_missing"})
            out_rows.append(row)
            continue

        if not (needs_budget or needs_deadline or needs_related_amounts):
            out_rows.append(row)
            continue

        stats["detail_attempted"] += 1
        cache_key = f"{no}-{ord_}"
        try:
            if cache_key in cache:
                item = cache[cache_key]
                count = item.get("count") or {}
                dm = item.get("detail") or {}
            else:
                count = get_count(session, no, ord_)
                if not count or int(count.get("bidPbancCnt") or 0) < 1:
                    item = {"cache_key": cache_key, "notice_no": no, "notice_ord": ord_, "count": count, "detail": {}, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                    cache[cache_key] = item
                    with cache_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    stats["count_not_found"] += 1
                    row["needs_manual_review_reason"] = append_reason(row.get("needs_manual_review_reason", ""), "g2b_detail_count_not_found")
                    failed.append({**row, "fallback_status": "count_not_found", "fallback_count_json": json.dumps(count, ensure_ascii=False)})
                    out_rows.append(row)
                    time.sleep(args.sleep)
                    continue
                dm = get_detail(session, no, ord_, count)
                item = {"cache_key": cache_key, "notice_no": no, "notice_ord": ord_, "count": count, "detail": dm, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                cache[cache_key] = item
                with cache_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                time.sleep(args.sleep)

            if not dm:
                failed.append({**row, "fallback_status": "detail_empty"})
                out_rows.append(row)
                continue

            stats["detail_success"] += 1
            final_budget, allocated, estimated, vat, other = pick_budget(dm)
            deadline = normalize_datetime(dm.get("slprRcptDdlnDt"))
            start_at = normalize_datetime(dm.get("slprRcptBgngDt"))

            if not clean(row.get("g2b_allocated_budget")) and allocated:
                row["g2b_allocated_budget"] = allocated
                stats["g2b_budget_columns_filled"] += 1
            if not clean(row.get("g2b_estimated_price")) and estimated:
                row["g2b_estimated_price"] = estimated
                stats["g2b_budget_columns_filled"] += 1
            if not clean(row.get("g2b_vat")) and vat:
                row["g2b_vat"] = vat
            if not clean(row.get("g2b_other_amount")) and other:
                row["g2b_other_amount"] = other
            if not clean(row.get("bid_submission_start_at")) and start_at:
                row["bid_submission_start_at"] = start_at
            if not clean(row.get("bid_submission_end_at")) and deadline:
                row["bid_submission_end_at"] = deadline

            snippet = detail_snippet(dm)
            if needs_budget and final_budget:
                row["final_project_budget"] = final_budget
                row["amount_source_origin"] = "g2b_notice_detail_related_amount"
                row["amount_evidence_label"] = "g2b_allocated_budget"
                row["amount_evidence_snippet"] = snippet
                row["needs_manual_review_reason"] = remove_reason(row.get("needs_manual_review_reason", ""), ("project_budget_not_found", "project_budget_low"))
                stats["budget_filled"] += 1
            if needs_deadline and deadline:
                row["final_bid_deadline"] = deadline
                row["deadline_source_origin"] = "g2b_notice_detail"
                row["deadline_evidence_label"] = "g2b_slprRcptDdlnDt"
                row["deadline_evidence_snippet"] = snippet
                row["needs_manual_review_reason"] = remove_reason(row.get("needs_manual_review_reason", ""), ("bid_deadline_not_found",))
                stats["deadline_filled"] += 1
            row["extraction_confidence"] = append_reason(row.get("extraction_confidence", ""), "g2b_detail_checked")
            out_rows.append(row)
        except Exception as exc:
            stats["errors"] += 1
            row["needs_manual_review_reason"] = append_reason(row.get("needs_manual_review_reason", ""), "g2b_detail_error")
            failed.append({**row, "fallback_status": "error", "fallback_error": repr(exc)})
            out_rows.append(row)
        if idx % 50 == 0 or idx == len(rows):
            print(f"processed {idx}/{len(rows)} stats={stats}")

    columns = list(df.columns)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)
    failed_columns = list(dict.fromkeys(columns + ["fallback_status", "fallback_error", "fallback_count_json"]))
    with failed_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=failed_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(failed)
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("saved:", output_path)
    print("failed:", failed_path)
    print("summary:", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
