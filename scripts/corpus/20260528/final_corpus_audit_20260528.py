from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3]))
PACKAGES = [
    ("125_full", ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix", "125", False),
    ("250_full", ROOT / "outputs/parsing_p4_hwpx_250_basic", "250", False),
    ("690_full", ROOT / "outputs/parsing_p4_hwpx_690_basic", "690", False),
    ("125_slim", ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim", "125", True),
    ("250_slim", ROOT / "outputs/parsing_p4_hwpx_250_basic_slim", "250", True),
    ("690_slim", ROOT / "outputs/parsing_p4_hwpx_690_basic_slim", "690", True),
]
G2B_CSV = ROOT / "data/g2b_notice_enrichment_690_strict_budget_reconciled.csv"

FORBIDDEN_TERMS = [
    "alias 보강",
    "alias보강",
    "alia보강",
    "alis보강",
    "수동 alias 보강",
    "alias/routing 보강",
    "보강(Q100)",
]

TAIL_NOISE_RE = re.compile(
    r"(개발비|H/W|예산액|예산:|입찰참가|제안서|계약방식|추진방법|표 섹션|rows|cols|제5조|평가위원|입찰 및|제출처|낙찰자|소프트웨어사업자)",
)

KEY_DOC_PATTERNS = [
    ("venture", "벤처확인종합관리시스템"),
    ("cms", "건설통합시스템"),
    ("q100_nano", "나노종합기술원"),
    ("asia_water", "아시아물위원회"),
    ("seoul_women", "여성가족재단"),
    ("mobile_office", "모바일오피스"),
    ("bioin", "BioIN"),
    ("k_water_accident", "사고분석"),
    ("afs_is", "AFSIS"),
]


def nfc(value: object) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except Exception as exc:
                raise RuntimeError(f"{path}:{line_no} JSON parse failed: {exc}") from exc


def load_g2b():
    by_source = {}
    with G2B_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("g2b_match_valid", "")).strip().lower() != "true":
                continue
            source = nfc(row.get("source_file"))
            if not source:
                continue
            by_source[source] = {
                "bid_notice_no": nfc(row.get("bid_notice_no")),
                "final_bid_deadline": nfc(row.get("final_bid_deadline") or row.get("bid_deadline")),
                "g2b_title": nfc(row.get("g2b_title")),
                "source_file": source,
            }
    return by_source


def value_from(obj: dict, key: str) -> str:
    if key in obj and obj.get(key) not in (None, ""):
        return nfc(obj.get(key))
    md = obj.get("metadata")
    if isinstance(md, dict) and md.get(key) not in (None, ""):
        return nfc(md.get(key))
    return ""


def scan_records(path: Path, id_key: str):
    ids = set()
    dup = 0
    line_count = 0
    forbidden_hits = []
    sources_by_file = defaultdict(list)
    g2b_rows = []
    durations = {}
    chunk_embed_false = 0
    chunk_toc = 0
    refs = []

    for line_no, obj in read_jsonl(path):
        line_count += 1
        row_id = nfc(obj.get(id_key))
        if row_id in ids:
            dup += 1
        ids.add(row_id)

        text_blob = json.dumps(obj, ensure_ascii=False)
        for term in FORBIDDEN_TERMS:
            if term in text_blob:
                forbidden_hits.append((path.name, line_no, term, row_id))

        source_file = nfc(obj.get("source_file_nfc") or obj.get("source_file") or value_from(obj, "source_file_nfc") or value_from(obj, "source_file"))
        if source_file:
            sources_by_file[source_file].append(row_id)

        if value_from(obj, "g2b_match_valid").lower() == "true":
            g2b_rows.append(
                {
                    "line_no": line_no,
                    "id": row_id,
                    "source_file": source_file,
                    "notice": value_from(obj, "final_notice_id") or value_from(obj, "bid_notice_no") or value_from(obj, "g2b_notice_id"),
                    "deadline": value_from(obj, "final_bid_deadline") or value_from(obj, "g2b_bid_deadline"),
                }
            )

        duration = nfc(obj.get("final_project_duration") or value_from(obj, "final_project_duration"))
        if source_file and duration:
            durations[source_file] = duration

        if id_key == "chunk_id":
            if obj.get("embed_enabled") is not True:
                chunk_embed_false += 1
            if obj.get("chunk_type") == "toc" or value_from(obj, "chunk_type") == "toc":
                chunk_toc += 1
            sr = obj.get("source_ref") or {}
            if isinstance(sr, dict):
                ref = nfc(sr.get("source_store_id"))
                if ref:
                    refs.append(ref)

    return {
        "ids": ids,
        "duplicate": dup,
        "line_count": line_count,
        "forbidden_hits": forbidden_hits,
        "sources_by_file": sources_by_file,
        "g2b_rows": g2b_rows,
        "durations": durations,
        "chunk_embed_false": chunk_embed_false,
        "chunk_toc": chunk_toc,
        "refs": refs,
    }


def audit_package(label: str, folder: Path, suffix: str, slim: bool, g2b_by_source: dict):
    chunk_path = folder / f"chunks_v2_{suffix}.jsonl"
    source_path = folder / f"source_store_v2_{suffix}.jsonl"
    validation_path = folder / "validation_report_v2.json"
    manifest_path = folder / "manifest.json"

    report = {
        "label": label,
        "folder": str(folder),
        "exists": folder.exists(),
        "validation_status": None,
        "validation_hash_ok": {},
        "manifest_hash_ok": {},
        "chunk_lines": None,
        "source_lines": None,
        "duplicate_chunk_id": None,
        "duplicate_source_store_id": None,
        "missing_source_ref": None,
        "forbidden_count": None,
        "slim_false_chunks": None,
        "slim_toc_chunks": None,
        "g2b_notice_mismatch": 0,
        "g2b_deadline_mismatch": 0,
        "g2b_notice_checked": 0,
        "g2b_deadline_checked": 0,
        "duration_doc_count": 0,
        "duration_tail_noise_count": 0,
        "duration_tail_noise_samples": [],
        "known_docs": {},
    }
    if not folder.exists():
        return report

    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    report["validation_status"] = validation.get("status")

    if chunk_path.exists():
        actual = sha1(chunk_path)
        for key in ("chunks_jsonl_sha1",):
            if validation.get(key):
                report["validation_hash_ok"][key] = actual == validation.get(key)
        if manifest.get("file_hashes", {}).get("chunks_v2_sha1"):
            report["manifest_hash_ok"]["chunks_v2_sha1"] = actual == manifest["file_hashes"]["chunks_v2_sha1"]

    if source_path.exists():
        actual = sha1(source_path)
        for key in ("source_store_jsonl_sha1",):
            if validation.get(key):
                report["validation_hash_ok"][key] = actual == validation.get(key)
        if manifest.get("file_hashes", {}).get("source_store_v2_sha1"):
            report["manifest_hash_ok"]["source_store_v2_sha1"] = actual == manifest["file_hashes"]["source_store_v2_sha1"]

    chunk = scan_records(chunk_path, "chunk_id")
    source = scan_records(source_path, "source_store_id")

    report["chunk_lines"] = chunk["line_count"]
    report["source_lines"] = source["line_count"]
    report["duplicate_chunk_id"] = chunk["duplicate"]
    report["duplicate_source_store_id"] = source["duplicate"]
    report["missing_source_ref"] = sum(1 for ref in chunk["refs"] if ref not in source["ids"])
    report["forbidden_count"] = len(chunk["forbidden_hits"]) + len(source["forbidden_hits"])
    report["slim_false_chunks"] = chunk["chunk_embed_false"] if slim else None
    report["slim_toc_chunks"] = chunk["chunk_toc"] if slim else None

    # Validation line counts when present.
    if validation.get("chunks_jsonl_line_count") is not None:
        report["validation_hash_ok"]["chunks_jsonl_line_count"] = chunk["line_count"] == validation.get("chunks_jsonl_line_count")
    if validation.get("source_store_jsonl_line_count") is not None:
        report["validation_hash_ok"]["source_store_jsonl_line_count"] = source["line_count"] == validation.get("source_store_jsonl_line_count")

    # G2B notice/deadline propagation check against the verified rows in the reconciled CSV.
    for row in source["g2b_rows"]:
        expected = g2b_by_source.get(row["source_file"])
        if not expected:
            continue
        exp_notice = expected["bid_notice_no"]
        exp_deadline = expected["final_bid_deadline"]
        if exp_notice:
            report["g2b_notice_checked"] += 1
            if row["notice"] != exp_notice:
                report["g2b_notice_mismatch"] += 1
        if exp_deadline:
            report["g2b_deadline_checked"] += 1
            if row["deadline"] != exp_deadline:
                report["g2b_deadline_mismatch"] += 1

    report["duration_doc_count"] = len(source["durations"])
    for source_file, duration in sorted(source["durations"].items()):
        if len(duration) > 90 or TAIL_NOISE_RE.search(duration):
            report["duration_tail_noise_count"] += 1
            if len(report["duration_tail_noise_samples"]) < 10:
                report["duration_tail_noise_samples"].append({"source_file": source_file, "duration": duration})

    # Known documents snapshot from source_store.
    snapshots = {}
    for line_no, obj in read_jsonl(source_path):
        source_file = nfc(obj.get("source_file_nfc") or obj.get("source_file"))
        for name, pattern in KEY_DOC_PATTERNS:
            if name in snapshots:
                continue
            if pattern in source_file or pattern in nfc(obj.get("project_name")) or pattern in nfc(obj.get("doc_key")):
                snapshots[name] = {
                    "source_file": source_file,
                    "budget": nfc(obj.get("final_budget")),
                    "budget_krw": nfc(obj.get("final_budget_krw")),
                    "budget_role": nfc(obj.get("budget_value_role")),
                    "notice": nfc(obj.get("final_notice_id") or obj.get("bid_notice_no")),
                    "deadline": nfc(obj.get("final_bid_deadline")),
                    "duration": nfc(obj.get("final_project_duration")),
                }
        if len(snapshots) == len(KEY_DOC_PATTERNS):
            break
    report["known_docs"] = snapshots

    return report


def main():
    g2b_by_source = load_g2b()
    print("G2B valid source rows:", len(g2b_by_source))
    print("G2B valid rows with notice:", sum(1 for v in g2b_by_source.values() if v["bid_notice_no"]))
    print("G2B valid rows with deadline:", sum(1 for v in g2b_by_source.values() if v["final_bid_deadline"]))
    print()

    reports = []
    for args in PACKAGES:
        report = audit_package(*args, g2b_by_source=g2b_by_source)
        reports.append(report)
        print("==", report["label"], "==")
        print("validation:", report["validation_status"])
        print("hash/line checks:", report["validation_hash_ok"])
        print("manifest checks:", report["manifest_hash_ok"])
        print(
            "counts:",
            {
                "chunks": report["chunk_lines"],
                "source_store": report["source_lines"],
                "dup_chunk": report["duplicate_chunk_id"],
                "dup_source": report["duplicate_source_store_id"],
                "missing_ref": report["missing_source_ref"],
                "forbidden": report["forbidden_count"],
                "slim_false": report["slim_false_chunks"],
                "slim_toc": report["slim_toc_chunks"],
            },
        )
        print(
            "g2b:",
            {
                "notice_checked": report["g2b_notice_checked"],
                "notice_mismatch": report["g2b_notice_mismatch"],
                "deadline_checked": report["g2b_deadline_checked"],
                "deadline_mismatch": report["g2b_deadline_mismatch"],
            },
        )
        print(
            "duration:",
            {
                "docs_with_duration": report["duration_doc_count"],
                "tail_noise_count": report["duration_tail_noise_count"],
                "samples": report["duration_tail_noise_samples"][:3],
            },
        )
        print("known_docs:", json.dumps(report["known_docs"], ensure_ascii=False)[:4000])
        print()

    fatal = []
    for r in reports:
        if r["validation_status"] != "PASS":
            fatal.append((r["label"], "validation_not_pass", r["validation_status"]))
        if any(v is False for v in r["validation_hash_ok"].values()):
            fatal.append((r["label"], "validation_hash_or_line_mismatch", r["validation_hash_ok"]))
        if any(v is False for v in r["manifest_hash_ok"].values()):
            fatal.append((r["label"], "manifest_hash_mismatch", r["manifest_hash_ok"]))
        for key in ("duplicate_chunk_id", "duplicate_source_store_id", "missing_source_ref", "forbidden_count", "g2b_notice_mismatch", "g2b_deadline_mismatch", "duration_tail_noise_count"):
            if r[key]:
                fatal.append((r["label"], key, r[key]))
        if "slim" in r["label"] and (r["slim_false_chunks"] or r["slim_toc_chunks"]):
            fatal.append((r["label"], "slim_policy_violation", (r["slim_false_chunks"], r["slim_toc_chunks"])))

    print("FATAL_SUMMARY:", "PASS" if not fatal else "FAIL")
    if fatal:
        for item in fatal:
            print(" -", item)


if __name__ == "__main__":
    main()
