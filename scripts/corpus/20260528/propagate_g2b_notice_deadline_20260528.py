from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3]))
CSV_PATH = ROOT / "data/g2b_notice_enrichment_690_strict_budget_reconciled.csv"

PACKAGES = [
    ("125", ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix", "chunks_v2_125.jsonl", ["source_store_v2_125.jsonl"], "pilot_docs_125.csv", "metadata_light_125.xlsx"),
    ("250", ROOT / "outputs/parsing_p4_hwpx_250_basic", "chunks_v2_250.jsonl", ["source_store_v2_250.jsonl", "source_store_250.jsonl"], "pilot_docs_250.csv", "metadata_light_250.xlsx"),
    ("690", ROOT / "outputs/parsing_p4_hwpx_690_basic", "chunks_v2_690.jsonl", ["source_store_v2_690.jsonl", "source_store_690.jsonl"], "pilot_docs_690.csv", "metadata_light_690.xlsx"),
    ("125_slim", ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim", "chunks_v2_125.jsonl", ["source_store_v2_125.jsonl"], "pilot_docs_125.csv", "metadata_light_125.xlsx"),
    ("250_slim", ROOT / "outputs/parsing_p4_hwpx_250_basic_slim", "chunks_v2_250.jsonl", ["source_store_v2_250.jsonl"], "pilot_docs_250.csv", "metadata_light_250.xlsx"),
    ("690_slim", ROOT / "outputs/parsing_p4_hwpx_690_basic_slim", "chunks_v2_690.jsonl", ["source_store_v2_690.jsonl"], "pilot_docs_690.csv", "metadata_light_690.xlsx"),
]

MARKERS = ["alia보강", "alis보강", "alias 보강", "alias보강", "수동 alias 보강", "보강(Q100)", "alias/routing 보강", "alias 보정"]


def nfc(value: object) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def sha(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def mib(path: Path) -> float:
    return round(path.stat().st_size / 1024 / 1024, 2)


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def split_notice(notice_id: str) -> tuple[str, str]:
    notice_id = str(notice_id or "").strip()
    if "-" not in notice_id:
        return notice_id, ""
    base, revision = notice_id.rsplit("-", 1)
    return base, revision


def load_updates() -> dict[str, dict[str, str]]:
    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    updates: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        if not truthy(row.get("g2b_match_valid")):
            continue
        source_file = nfc(row.get("source_file"))
        notice_id = str(row.get("bid_notice_no") or "").strip()
        title = str(row.get("g2b_title") or "").strip()
        deadline = str(row.get("final_bid_deadline") or row.get("bid_deadline") or row.get("bid_submission_end_at") or "").strip()
        if not notice_id and not deadline:
            continue
        raw = {}
        try:
            raw = json.loads(row.get("raw_master_json") or "{}")
        except Exception:
            raw = {}
        base, revision = split_notice(notice_id)
        updates[source_file] = {
            "bid_notice_no": notice_id,
            "final_notice_id": notice_id,
            "g2b_notice_id": notice_id,
            "g2b_notice_base": base,
            "g2b_notice_revision": revision,
            "g2b_title": title,
            "g2b_notice_kind": str(raw.get("구분") or "").strip(),
            "g2b_notice_agency": str(raw.get("공고기관") or "").strip(),
            "g2b_demand_agency": str(raw.get("수요기관") or "").strip(),
            "final_bid_deadline": deadline,
            "g2b_bid_deadline": deadline,
            "bid_deadline_status": "g2b_matched",
            "g2b_bid_deadline_source": "g2b_master_cleaned.csv:게시일시(입찰마감일시)",
            "notice_id_status": "g2b_matched",
            "g2b_match_status": "matched_active",
            "g2b_match_valid": "true",
        }
    return updates


UPDATES = load_updates()


def source_file_of(row: dict) -> str:
    md = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return nfc(row.get("source_file_nfc") or row.get("source_file") or md.get("source_file_nfc") or md.get("source_file"))


def apply_fields(obj: dict, update: dict[str, str]) -> None:
    for key, value in update.items():
        if value != "":
            obj[key] = value


def maybe_update_deadline_text(text: object, update: dict[str, str], row: dict) -> object:
    if not isinstance(text, str):
        return text
    md = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    fact_type = str(row.get("fact_type") or md.get("fact_type") or "")
    section_path = str(row.get("section_path") or md.get("section_path") or "")
    chunk_type = str(row.get("chunk_type") or md.get("chunk_type") or row.get("source_type") or "")
    if "bid_deadline" not in fact_type and "bid_deadline" not in section_path and chunk_type != "fact_candidates":
        return text
    deadline = update.get("final_bid_deadline", "")
    notice_id = update.get("bid_notice_no", "")
    title = update.get("g2b_title", "")
    if deadline:
        text = re.sub(r"(입찰마감일시/마감일/제안서 제출마감:\\s*)[^|\\n]+", rf"\\g<1>{deadline} ", text)
        text = re.sub(r"(입찰마감일:\\s*)[^|\\n]+", rf"\\g<1>{deadline} ", text)
        text = re.sub(r"(마감일시:\\s*)[^|\\n]+", rf"\\g<1>{deadline} ", text)
    if notice_id:
        text = re.sub(r"(G2B 공고번호:\\s*)[^|\\n]+", rf"\\g<1>{notice_id} ", text)
    if title:
        text = re.sub(r"(G2B 공고명:\\s*)[^|\\n]+", rf"\\g<1>{title} ", text)
    return text


def process_jsonl(path: Path) -> int:
    rows = []
    changed = 0
    for row in iter_jsonl(path):
        sf = source_file_of(row)
        update = UPDATES.get(sf)
        if update:
            before = json.dumps(row, ensure_ascii=False, sort_keys=True)
            apply_fields(row, update)
            md = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
            if md is not None:
                apply_fields(md, update)
            for key in ("content", "full_text"):
                if key in row:
                    row[key] = maybe_update_deadline_text(row[key], update, row)
            if before != json.dumps(row, ensure_ascii=False, sort_keys=True):
                changed += 1
        rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    if changed:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(rows), encoding="utf-8")
        tmp.replace(path)
    return changed


def process_table(path: Path) -> int:
    if not path.exists():
        return 0
    if path.suffix == ".csv":
        df = pd.read_csv(path, dtype=str).fillna("")
    else:
        df = pd.read_excel(path, dtype=str).fillna("")
    changed = 0
    for i, row in df.iterrows():
        update = UPDATES.get(nfc(row.get("source_file") or row.get("source_file_nfc") or ""))
        if not update:
            continue
        before = df.loc[i].copy()
        for col, key in [
            ("bid_notice_no", "bid_notice_no"),
            ("final_notice_id", "final_notice_id"),
            ("g2b_notice_id", "g2b_notice_id"),
            ("g2b_title", "g2b_title"),
            ("final_bid_deadline", "final_bid_deadline"),
            ("g2b_bid_deadline", "g2b_bid_deadline"),
            ("bid_deadline_status", "bid_deadline_status"),
            ("notice_id_status", "notice_id_status"),
        ]:
            if col in df.columns and update.get(key):
                df.loc[i, col] = update[key]
        if not before.equals(df.loc[i]):
            changed += 1
    if changed:
        if path.suffix == ".csv":
            df.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            df.to_excel(path, index=False)
    return changed


def refresh_package(folder: Path, chunks_name: str, source_names: list[str], pilot_name: str, xlsx_name: str) -> None:
    chunks = folder / chunks_name
    source = folder / source_names[0]
    chunk_ids, refs, source_ids = [], [], []
    chunk_type_counts, fact_type_counts = {}, {}
    embed_enabled = 0
    forbidden = 0
    for row in iter_jsonl(chunks):
        md = row.get("metadata") or {}
        chunk_ids.append(row.get("chunk_id"))
        refs.append(str((row.get("source_ref") or {}).get("source_store_id") or ""))
        if row.get("embed_enabled") is True:
            embed_enabled += 1
        chunk_type = str(row.get("chunk_type") or md.get("chunk_type") or "")
        chunk_type_counts[chunk_type] = chunk_type_counts.get(chunk_type, 0) + 1
        fact_type = str(row.get("fact_type") or md.get("fact_type") or "")
        if fact_type:
            fact_type_counts[fact_type] = fact_type_counts.get(fact_type, 0) + 1
        txt = json.dumps(row, ensure_ascii=False)
        if any(marker in txt for marker in MARKERS):
            forbidden += 1
    for row in iter_jsonl(source):
        source_ids.append(str(row.get("source_store_id") or ""))
        txt = json.dumps(row, ensure_ascii=False)
        if any(marker in txt for marker in MARKERS):
            forbidden += 1
    source_set = set(source_ids)
    missing_refs = sum(1 for ref in refs if not ref or ref not in source_set)
    status = "PASS" if not forbidden and not missing_refs and len(chunk_ids) == len(set(chunk_ids)) and len(source_ids) == len(set(source_ids)) else "FAIL"
    for name in ("validation_report_v2.json", "validation_report.json"):
        path = folder / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update({
            "status": status,
            "chunk_count": len(chunk_ids),
            "chunks_jsonl_line_count": len(chunk_ids),
            "source_store_count": len(source_ids),
            "source_store_jsonl_line_count": len(source_ids),
            "duplicate_chunk_id_count": len(chunk_ids) - len(set(chunk_ids)),
            "duplicate_source_store_id_count": len(source_ids) - len(set(source_ids)),
            "missing_source_store_ref": missing_refs,
            "missing_source_ref_count": missing_refs,
            "embed_enabled_count": embed_enabled,
            "chunk_type_counts": chunk_type_counts,
            "fact_type_counts": fact_type_counts,
            "chunks_jsonl_file_size_mib": mib(chunks),
            "source_store_file_size_mib": mib(source),
            "source_store_jsonl_file_size_mib": mib(source),
            "chunks_jsonl_sha1": sha(chunks),
            "source_store_jsonl_sha1": sha(source),
            "g2b_notice_deadline_propagation_patch": "20260528",
        })
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = folder / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        hashes = data.setdefault("file_hashes", {})
        for key, path in [
            ("chunks_v2_sha1", chunks),
            ("source_store_v2_sha1", source),
            ("source_store_sha1", source),
            ("pilot_docs_sha1", folder / pilot_name),
            ("metadata_light_sha1", folder / xlsx_name),
            ("validation_v2_sha1", folder / "validation_report_v2.json"),
            ("validation_sha1", folder / "validation_report.json"),
            ("readme_sha1", folder / "README.md"),
            ("json_key_description_sha1", folder / "json_key_description.md"),
        ]:
            if path.exists():
                hashes[key] = sha(path)
        data.setdefault("post_build_datafixes", []).append({
            "patch": "g2b_notice_deadline_propagation_20260528",
            "source": str(CSV_PATH),
            "scope": "g2b_match_valid=true rows",
        })
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    report = {"update_source_files": len(UPDATES)}
    for _, folder, chunks_name, source_names, pilot_name, xlsx_name in PACKAGES:
        if not folder.exists():
            continue
        report[str(folder / chunks_name)] = process_jsonl(folder / chunks_name)
        for source_name in source_names:
            path = folder / source_name
            if path.exists():
                report[str(path)] = process_jsonl(path)
        report[str(folder / pilot_name)] = process_table(folder / pilot_name)
        report[str(folder / xlsx_name)] = process_table(folder / xlsx_name)
        refresh_package(folder, chunks_name, source_names, pilot_name, xlsx_name)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
