from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3]))
PARSING_SRC = PROJECT_ROOT / "src" / "parsing"

sys.path.insert(0, str(PARSING_SRC))

import rfp_parsing_v1_v2_lib as rfp  # noqa: E402
import rfp_p4_hwpx_corpus as p4  # noqa: E402


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def load_original_inventory(project_root: Path) -> pd.DataFrame:
    inventory = rfp.build_original_inventory(project_root / "data" / "original_data_list").copy()
    if inventory.empty:
        raise FileNotFoundError("원본 RFP 파일을 찾지 못했습니다: data/original_data_list")
    inventory["_original_order"] = range(1, len(inventory) + 1)
    inventory["source_path"] = inventory["source_path"].astype(str)
    inventory["source_file"] = inventory["source_file"].astype(str)
    inventory["file_type"] = inventory["file_type"].astype(str).str.lower().str.strip()
    inventory["norm_name"] = inventory["source_file"].map(rfp.normalize_doc_name)
    return inventory


def eval_norms(project_root: Path) -> set[str]:
    eval_df = rfp.load_eval_ground_truth_docs(project_root / "data" / "eval")
    if eval_df.empty:
        return set()
    return set(eval_df["norm_name"].dropna().astype(str))


def select_rows(project_root: Path, limit: int, output_dir: Path) -> tuple[pd.DataFrame, dict]:
    base = load_original_inventory(project_root)
    if limit > len(base):
        raise ValueError(f"requested limit={limit}, but only {len(base)} original files exist")

    eval_set = eval_norms(project_root)
    base["is_eval_ground_truth"] = base["norm_name"].isin(eval_set)
    duplicate_norm_count = int(base["norm_name"].duplicated().sum())

    if limit == len(base):
        selected = base.copy()
        selection_rule = (
            "full original_data_list inventory: parse original hwp/pdf files; "
            "hwp uses matching data/hwpx_664 conversion when available; no enrichment CSV used for corpus selection"
        )
    else:
        priority = {"hwp": 0, "hwpx": 0, "pdf": 1}
        work = base.copy()
        work["_file_priority"] = work["file_type"].map(priority).fillna(2).astype(int)
        work = work.sort_values(
            ["is_eval_ground_truth", "_file_priority", "_original_order"],
            ascending=[False, True, True],
        )
        work = work.drop_duplicates(subset=["norm_name"], keep="first")
        selected = work.head(limit).drop(columns=["_file_priority"]).copy()
        selection_rule = (
            "eval-covered sample from data/original_data_list: include matched eval ground-truth docs first, "
            "deduplicate normalized source names preferring HWP/HWPX over PDF, then fill by original inventory order; "
            "hwp uses matching data/hwpx_664 conversion when available; no enrichment CSV used for corpus selection"
        )

    selected = selected.reset_index(drop=True)
    selected.insert(0, "pilot_index", range(1, len(selected) + 1))
    selected["rank_index"] = selected["pilot_index"]
    selected["doc_id"] = selected["source_file"].map(p4.make_doc_id)
    selected["doc_key"] = selected["source_file"].map(p4.make_doc_key)
    selected["pilot_doc_id"] = selected["doc_id"].map(lambda x: "D" + str(x).replace("doc_", "")[:10])
    selected = selected.drop(columns=[c for c in ["_original_order"] if c in selected.columns])

    output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_dir / f"pilot_docs_{limit}.csv", index=False, encoding="utf-8-sig")

    return selected, {
        "selection_rule": selection_rule,
        "sample_source": "data/original_data_list",
        "document_count": int(len(selected)),
        "eval_ground_truth_norms_available": int(len(eval_set)),
        "eval_physical_source_docs_included": int(selected["is_eval_ground_truth"].sum()),
        "additional_sampled_docs": int((~selected["is_eval_ground_truth"]).sum()),
        "input_duplicate_norm_name_count": duplicate_norm_count,
        "selected_duplicate_norm_name_count": int(selected["norm_name"].duplicated().sum()),
        "base_corpus_policy": {
            "g2b_enrichment_amounts_applied": False,
            "g2b_enrichment_csv_used_for_selection": False,
            "source_of_truth": "original hwp/pdf files; converted hwpx only as parsing representation for hwp originals",
            "reason": "Base corpus generation parses source documents first. G2B/reconciled CSV may only be used later for missing-field enrichment after source-document inspection.",
        },
    }


def install_sample_loader() -> None:
    def _load_sample_rows(project_root: Path, limit: int, output_dir: Path):
        return select_rows(project_root, int(limit), output_dir)

    p4.load_sample_rows = _load_sample_rows


def add_compatibility_files(output_dir: Path, limit: int) -> None:
    source_store = output_dir / f"source_store_{limit}.jsonl"
    source_store_v2 = output_dir / f"source_store_v2_{limit}.jsonl"
    validation = output_dir / "validation_report.json"
    validation_v2 = output_dir / "validation_report_v2.json"
    if source_store.exists():
        shutil.copy2(source_store, source_store_v2)
    if validation.exists():
        shutil.copy2(validation, validation_v2)

    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["base_corpus_build_note"] = {
        "created_by": "build_p4_original_corpus_250_690.py",
        "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "input_inventory": "data/original_data_list",
        "hwp_parse_policy": "use data/hwpx_664 converted HWPX when normalized original HWP filename matches; otherwise hwp_fallback",
        "pdf_parse_policy": "parse PDF original directly",
        "g2b_amount_backfill_applied": False,
        "numeric_role_qc_completed": False,
        "next_step": "Run rfp-corpus-build-qc source-first budget role QC before treating this as final data.",
    }
    manifest["source_store_v2_file"] = source_store_v2.name if source_store_v2.exists() else manifest.get("source_store_v2_file", "")
    manifest["validation_v2_file"] = validation_v2.name if validation_v2.exists() else manifest.get("validation_v2_file", "")
    hashes = manifest.setdefault("file_hashes", {})
    for key, path in {
        "chunks_v1_sha1": output_dir / f"chunks_v1_{limit}.jsonl",
        "chunks_v2_sha1": output_dir / f"chunks_v2_{limit}.jsonl",
        "source_store_v1_sha1": output_dir / f"source_store_v1_{limit}.jsonl",
        "source_store_v2_sha1": source_store_v2,
        "source_store_sha1": source_store,
        "pilot_docs_sha1": output_dir / f"pilot_docs_{limit}.csv",
        "metadata_light_sha1": output_dir / f"metadata_light_{limit}.xlsx",
        "validation_v2_sha1": validation_v2,
        "validation_sha1": validation,
    }.items():
        if path.exists():
            hashes[key] = file_sha1(path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_output(output_dir: Path, limit: int) -> dict:
    report_path = output_dir / "validation_report_v2.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    paths = {
        "chunks_v2": output_dir / f"chunks_v2_{limit}.jsonl",
        "source_store_v2": output_dir / f"source_store_v2_{limit}.jsonl",
        "source_store_alias": output_dir / f"source_store_{limit}.jsonl",
        "pilot_docs": output_dir / f"pilot_docs_{limit}.csv",
        "metadata_light": output_dir / f"metadata_light_{limit}.xlsx",
        "manifest": output_dir / "manifest.json",
        "validation_report_v2": report_path,
    }
    return {
        "output_dir": str(output_dir),
        "status": report.get("status"),
        "document_count": report.get("document_count"),
        "chunk_count": report.get("chunk_count"),
        "embed_enabled_count": report.get("embed_enabled_count"),
        "source_store_count": report.get("source_store_count"),
        "files": {
            name: {
                "exists": path.exists(),
                "size_mib": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
                "sha1": file_sha1(path) if path.exists() else "",
                "line_count": line_count(path) if path.suffix == ".jsonl" and path.exists() else None,
            }
            for name, path in paths.items()
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, choices=[250, 690], required=True)
    ap.add_argument("--project-root", default=str(PROJECT_ROOT))
    ap.add_argument("--output-dir-name", default="")
    ap.add_argument("--progress-every", type=int, default=25)
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    output_dir_name = args.output_dir_name or f"parsing_p4_hwpx_{args.limit}_basic"
    install_sample_loader()
    result = p4.write_p4_corpus(
        project_root,
        limit=args.limit,
        verbose=True,
        progress_every=args.progress_every,
        output_dir_name=output_dir_name,
    )
    output_dir = Path(result["output_dir"])
    add_compatibility_files(output_dir, args.limit)
    summary = summarize_output(output_dir, args.limit)
    summary_path = output_dir / f"basic_corpus_summary_{args.limit}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
