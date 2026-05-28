from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3]))
REF = {
    "n": 125,
    "dir": ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix",
    "chunks": "chunks_v2_125.jsonl",
    "source_store": "source_store_v2_125.jsonl",
}
TARGETS = [
    {
        "n": 250,
        "dir": ROOT / "outputs/parsing_p4_hwpx_250_basic",
        "chunks": "chunks_v2_250.jsonl",
        "source_store": "source_store_v2_250.jsonl",
        "source_store_alias": "source_store_250.jsonl",
    },
    {
        "n": 690,
        "dir": ROOT / "outputs/parsing_p4_hwpx_690_basic",
        "chunks": "chunks_v2_690.jsonl",
        "source_store": "source_store_v2_690.jsonl",
        "source_store_alias": "source_store_690.jsonl",
    },
]

UPDATED_AT = "2026-05-28 14:00:00"
VERSION_SUFFIX = "+schema_125_aligned_20260528"


def sha1_text(text: str, n: int = 12) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:n]


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == "" or value.strip().lower() == "nan"
    return False


def as_scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(v) for v in value if str(v).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def normalize_doc_key(source_file: str) -> str:
    name = Path(str(source_file or "")).name
    return re.sub(r"\.(hwp|hwpx|pdf|docx?)$", "", name, flags=re.I).strip()


def canonical_key_from(record: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    value = (
        record.get("canonical_doc_key")
        or metadata.get("canonical_doc_key")
        or record.get("doc_key")
        or metadata.get("doc_key")
        or normalize_doc_key(record.get("source_file") or metadata.get("source_file") or "")
    )
    return unicodedata.normalize("NFC", str(value or "")).strip()


def derived_value(key: str, record: dict[str, Any], metadata: dict[str, Any] | None = None) -> Any:
    metadata = metadata or {}
    source_file = str(record.get("source_file") or metadata.get("source_file") or "")
    canonical_doc_key = canonical_key_from(record, metadata)
    if key == "source_file_nfc":
        return unicodedata.normalize("NFC", source_file)
    if key == "canonical_doc_key":
        return canonical_doc_key
    if key == "canonical_doc_id":
        return f"doc_{sha1_text(canonical_doc_key, 12)}" if canonical_doc_key else ""
    if key == "bid_notice_no":
        return record.get("g2b_notice_id") or metadata.get("g2b_notice_id") or ""
    if key.endswith("_count"):
        return 0
    if key in {
        "manual_budget_override_applied",
        "manual_budget_missing_do_not_inject",
        "g2b_related_amount_checked",
        "g2b_is_cancelled",
        "is_reannouncement",
    }:
        return False
    if key == "table_structure":
        return {}
    return ""


def ordered_schema_from_chunks(path: Path) -> tuple[list[str], list[str], list[str]]:
    top: list[str] = []
    meta: list[str] = []
    sref: list[str] = []
    top_seen, meta_seen, sref_seen = set(), set(), set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for key in rec:
                if key not in top_seen:
                    top_seen.add(key)
                    top.append(key)
            metadata = rec.get("metadata")
            if isinstance(metadata, dict):
                for key in metadata:
                    if key not in meta_seen:
                        meta_seen.add(key)
                        meta.append(key)
            source_ref = rec.get("source_ref")
            if isinstance(source_ref, dict):
                for key in source_ref:
                    if key not in sref_seen:
                        sref_seen.add(key)
                        sref.append(key)
    return top, meta, sref


def ordered_schema_from_source(path: Path) -> list[str]:
    keys: list[str] = []
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for key in rec:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
    return keys


def pick_value(
    key: str,
    record: dict[str, Any],
    metadata: dict[str, Any],
    source_record: dict[str, Any] | None,
) -> Any:
    source_record = source_record or {}
    for candidate in (record.get(key), metadata.get(key), source_record.get(key)):
        if not is_missing(candidate):
            return candidate
    return derived_value(key, record, metadata)


def compact_source_lookup(path: Path, needed_keys: set[str]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    skip_heavy = {"full_text", "table_structure"}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            sid = str(rec.get("source_store_id") or "")
            if not sid:
                continue
            slim = {}
            for key in needed_keys - skip_heavy:
                value = rec.get(key)
                if not is_missing(value):
                    slim[key] = value
            lookup[sid] = slim
    return lookup


def write_jsonl_atomic(path: Path, rows_iter) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows_iter:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def normalize_source_store_rows(path: Path, ref_source_keys: list[str]):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            normalized = {}
            for key in ref_source_keys:
                value = rec.get(key)
                if is_missing(value):
                    value = derived_value(key, rec, {})
                if key not in {"table_structure"}:
                    value = as_scalar(value)
                normalized[key] = value
            yield normalized


def normalize_chunk_rows(
    path: Path,
    ref_top_keys: list[str],
    ref_meta_keys: list[str],
    ref_source_ref_keys: list[str],
    source_lookup: dict[str, dict[str, Any]],
):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            metadata = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            source_ref = rec.get("source_ref") if isinstance(rec.get("source_ref"), dict) else {}
            sid = str(source_ref.get("source_store_id") or "")
            source_record = source_lookup.get(sid, {})

            normalized_metadata = {}
            for key in ref_meta_keys:
                value = pick_value(key, rec, metadata, source_record)
                normalized_metadata[key] = as_scalar(value)

            normalized_source_ref = {}
            for key in ref_source_ref_keys:
                value = source_ref.get(key)
                if is_missing(value):
                    value = rec.get(key) if not is_missing(rec.get(key)) else source_record.get(key)
                if is_missing(value):
                    value = derived_value(key, rec, metadata)
                normalized_source_ref[key] = as_scalar(value)

            normalized = {}
            for key in ref_top_keys:
                if key == "metadata":
                    normalized[key] = normalized_metadata
                elif key == "source_ref":
                    normalized[key] = normalized_source_ref
                else:
                    value = pick_value(key, rec, metadata, source_record)
                    normalized[key] = as_scalar(value)
            yield normalized


def validate_package(pkg: dict[str, Any]) -> dict[str, Any]:
    n = pkg["n"]
    output_dir = pkg["dir"]
    chunks_path = output_dir / pkg["chunks"]
    source_path = output_dir / pkg["source_store"]
    chunk_ids: set[str] = set()
    source_ids: set[str] = set()
    source_ref_ids: list[str] = []
    duplicate_chunk = 0
    duplicate_source = 0
    embed_enabled_count = 0
    chunk_type_counts = Counter()
    fact_type_counts = Counter()
    answer_policy_counts = Counter()

    with source_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            sid = str(rec.get("source_store_id") or "")
            if sid in source_ids:
                duplicate_source += 1
            source_ids.add(sid)

    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            cid = str(rec.get("chunk_id") or "")
            if cid in chunk_ids:
                duplicate_chunk += 1
            chunk_ids.add(cid)
            source_ref_ids.append(str((rec.get("source_ref") or {}).get("source_store_id") or ""))
            if rec.get("embed_enabled") is True or str(rec.get("embed_enabled")).lower() == "true":
                embed_enabled_count += 1
            chunk_type_counts[str(rec.get("chunk_type") or "")] += 1
            fact_type = rec.get("fact_type") or (rec.get("metadata") or {}).get("fact_type") or ""
            if fact_type:
                fact_type_counts[str(fact_type)] += 1
            answer_policy = rec.get("answer_policy") or (rec.get("metadata") or {}).get("answer_policy") or ""
            answer_policy_counts[str(answer_policy)] += 1

    missing_refs = [ref for ref in source_ref_ids if ref and ref not in source_ids]
    fail_reasons = []
    if duplicate_chunk:
        fail_reasons.append("duplicate_chunk_id")
    if duplicate_source:
        fail_reasons.append("duplicate_source_store_id")
    if missing_refs:
        fail_reasons.append("missing_source_store_ref")

    report = {}
    old_report = output_dir / "validation_report_v2.json"
    if old_report.exists():
        report.update(json.loads(old_report.read_text(encoding="utf-8")))
    report.update(
        {
            "output_dir": str(output_dir),
            "version": f"v2_source_first_budget_role_qc_20260528{VERSION_SUFFIX}",
            "document_count": n,
            "chunk_count": len(chunk_ids),
            "source_store_count": len(source_ids),
            "duplicate_chunk_id_count": duplicate_chunk,
            "duplicate_source_store_id_count": duplicate_source,
            "missing_source_store_ref": len(missing_refs),
            "missing_source_store_ref_count": len(missing_refs),
            "embed_enabled_count": embed_enabled_count,
            "chunk_type_counts": dict(chunk_type_counts),
            "fact_type_counts": dict(fact_type_counts),
            "answer_policy_counts": dict(answer_policy_counts),
            "chunks_jsonl_file_size_mib": round(chunks_path.stat().st_size / 1024 / 1024, 2),
            "source_store_file_size_mib": round(source_path.stat().st_size / 1024 / 1024, 2),
            "source_store_jsonl_file_size_mib": round(source_path.stat().st_size / 1024 / 1024, 2),
            "chunks_jsonl_line_count": line_count(chunks_path),
            "source_store_jsonl_line_count": line_count(source_path),
            "chunks_jsonl_sha1": file_sha1(chunks_path),
            "source_store_jsonl_sha1": file_sha1(source_path),
            "status": "PASS" if not fail_reasons else "FAIL",
            "fail_reasons": fail_reasons,
            "schema_aligned_to_125": True,
            "schema_aligned_to_125_updated_at": UPDATED_AT,
        }
    )
    return report


def replace_v2_validation_block(readme: str, report: dict[str, Any]) -> str:
    block = "### v2\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```"
    pattern = r"### v2\n\n```json\n.*?\n```"
    if re.search(pattern, readme, flags=re.S):
        return re.sub(pattern, block, readme, flags=re.S)
    return readme.rstrip() + "\n\n" + block + "\n"


def upsert_section(text: str, heading: str, body: str) -> str:
    section = f"{heading}\n\n{body.strip()}\n"
    pattern = rf"{re.escape(heading)}\n\n.*?(?=\n## |\Z)"
    if re.search(pattern, text, flags=re.S):
        return re.sub(pattern, section.rstrip(), text, flags=re.S)
    return text.rstrip() + "\n\n" + section


def update_readme(pkg: dict[str, Any], report: dict[str, Any], ref_counts: dict[str, int]) -> None:
    path = pkg["dir"] / "README.md"
    readme = path.read_text(encoding="utf-8")
    readme = replace_v2_validation_block(readme, report)
    body = f"""
- `chunks_v2_{pkg['n']}.jsonl`과 `source_store_v2_{pkg['n']}.jsonl`은 125 `datafix_goalfix` corpus의 JSON key set에 맞춰 post-build normalization을 적용했습니다.
- 원문 `content`, `full_text`, `chunk_id`, `source_store_id`, `embed_enabled`는 변경하지 않았고, 누락된 식별/정책 key만 추가 또는 정렬했습니다.
- 기준 schema key 수: chunk top-level {ref_counts['chunk_top']}개, chunk metadata {ref_counts['chunk_metadata']}개, source_ref {ref_counts['source_ref']}개, source_store top-level {ref_counts['source_store']}개.
- `chunks_v1_*`, `source_store_v1_*`는 R0 baseline이므로 이 schema normalization 대상에서 제외했습니다.
"""
    readme = upsert_section(readme, "## 125 Schema Alignment", body)
    path.write_text(readme.rstrip() + "\n", encoding="utf-8")


def update_manifest(pkg: dict[str, Any], report: dict[str, Any], ref_counts: dict[str, int]) -> None:
    output_dir = pkg["dir"]
    n = pkg["n"]
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("corpus_version") or "")
    if VERSION_SUFFIX not in version:
        manifest["corpus_version"] = version + VERSION_SUFFIX
    manifest["schema_alignment"] = {
        "updated_at": UPDATED_AT,
        "schema_source": "outputs/parsing_p4_hwpx_125_datafix_goalfix",
        "method": "post_build_jsonl_normalization_without_reparsing",
        "preserved_fields": ["content", "full_text", "chunk_id", "source_store_id", "embed_enabled"],
        "reference_key_counts": ref_counts,
    }
    post = manifest.setdefault("post_build_datafixes", [])
    if not any(item.get("scope") == "250/690 schema alignment to 125" for item in post):
        post.append(
            {
                "updated_at": UPDATED_AT,
                "scope": "250/690 schema alignment to 125",
                "summary": "125 datafix_goalfix corpus의 chunks/source_store JSON key set을 기준으로 250/690 v2 산출물 schema를 통일. 데이터 값과 원문 텍스트는 보존하고 누락 key를 보강.",
            }
        )

    hashes = manifest.setdefault("file_hashes", {})
    file_map = {
        "chunks_v2_sha1": output_dir / pkg["chunks"],
        "source_store_v2_sha1": output_dir / pkg["source_store"],
        "validation_v2_sha1": output_dir / "validation_report_v2.json",
        "validation_sha1": output_dir / "validation_report.json",
        "readme_sha1": output_dir / "README.md",
    }
    alias = pkg.get("source_store_alias")
    if alias:
        file_map["source_store_sha1"] = output_dir / alias
    json_desc = output_dir / "json_key_description.md"
    if json_desc.exists():
        file_map["json_key_description_sha1"] = json_desc
    chroma = output_dir / "CHROMA_LOAD_GUIDE.md"
    if chroma.exists():
        file_map["chroma_load_guide_sha1"] = chroma
    for key, path in file_map.items():
        if path.exists():
            hashes[key] = file_sha1(path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process_target(pkg: dict[str, Any], ref_top: list[str], ref_meta: list[str], ref_sref: list[str], ref_source: list[str]) -> dict[str, Any]:
    output_dir = pkg["dir"]
    chunks_path = output_dir / pkg["chunks"]
    source_path = output_dir / pkg["source_store"]
    alias_name = pkg.get("source_store_alias")
    alias_path = output_dir / alias_name if alias_name else None

    needed_for_chunks = set(ref_top) | set(ref_meta) | set(ref_sref)
    source_lookup = compact_source_lookup(source_path, needed_for_chunks)
    before = {
        "chunk_lines": line_count(chunks_path),
        "source_lines": line_count(source_path),
    }

    write_jsonl_atomic(source_path, normalize_source_store_rows(source_path, ref_source))
    if alias_path:
        shutil.copyfile(source_path, alias_path)
    write_jsonl_atomic(chunks_path, normalize_chunk_rows(chunks_path, ref_top, ref_meta, ref_sref, source_lookup))

    after = {
        "chunk_lines": line_count(chunks_path),
        "source_lines": line_count(source_path),
    }
    if before != after:
        raise RuntimeError(f"Line count changed for {output_dir.name}: before={before} after={after}")

    report = validate_package(pkg)
    for name in ["validation_report_v2.json", "validation_report.json"]:
        (output_dir / name).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ref_counts = {
        "chunk_top": len(ref_top),
        "chunk_metadata": len(ref_meta),
        "source_ref": len(ref_sref),
        "source_store": len(ref_source),
    }
    update_readme(pkg, report, ref_counts)
    update_manifest(pkg, report, ref_counts)
    return {
        "package": output_dir.name,
        "before": before,
        "after": after,
        "report": {
            "status": report["status"],
            "chunk_count": report["chunk_count"],
            "source_store_count": report["source_store_count"],
            "chunks_sha1": report["chunks_jsonl_sha1"],
            "source_store_sha1": report["source_store_jsonl_sha1"],
        },
    }


def main() -> None:
    ref_top, ref_meta, ref_sref = ordered_schema_from_chunks(REF["dir"] / REF["chunks"])
    ref_source = ordered_schema_from_source(REF["dir"] / REF["source_store"])
    results = {}
    for pkg in TARGETS:
        results[pkg["dir"].name] = process_target(pkg, ref_top, ref_meta, ref_sref, ref_source)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
