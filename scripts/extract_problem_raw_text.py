#!/usr/bin/env python3
"""Extract text from raw HWP/PDF files relevant to PEFT review rows."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zlib
from pathlib import Path
from typing import Any

import olefile
from pypdf import PdfReader


DEFAULT_REVIEW_PATH = Path("outputs/peft/salvaged_conservative/label_review_needed.jsonl")
DEFAULT_RAW_DIR = Path("data/files_advanced")
DEFAULT_OUTPUT_DIR = Path("outputs/peft/raw_original_review/extracted_text")


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def normalize_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"\.(hwp|hwpx|pdf)$", "", text)
    text = re.sub(r"[\s_\-()[\]{}'\".,/\\:;|·~]+", "", text)
    return text


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def hwp_is_compressed(ole: olefile.OleFileIO) -> bool:
    header = ole.openstream("FileHeader").read()
    if len(header) < 40:
        return False
    flags = int.from_bytes(header[36:40], "little")
    return bool(flags & 1)


def clean_hwp_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_hwp(path: Path) -> str:
    chunks: list[str] = []
    with olefile.OleFileIO(str(path)) as ole:
        compressed = hwp_is_compressed(ole)
        section_paths = [
            item
            for item in ole.listdir()
            if len(item) >= 2 and item[0] == "BodyText" and item[1].startswith("Section")
        ]
        section_paths.sort(key=lambda item: item[1])
        for section_path in section_paths:
            data = ole.openstream(section_path).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                header = int.from_bytes(data[pos : pos + 4], "little")
                pos += 4
                tag_id = header & 0x3FF
                size = (header >> 20) & 0xFFF
                if size == 0xFFF:
                    if pos + 4 > len(data):
                        break
                    size = int.from_bytes(data[pos : pos + 4], "little")
                    pos += 4
                payload = data[pos : pos + size]
                pos += size
                # HWPTAG_PARA_TEXT
                if tag_id == 67:
                    chunks.append(payload.decode("utf-16le", errors="ignore"))
    return clean_hwp_text("\n".join(chunks))


def extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return clean_hwp_text("\n".join(pages))


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".hwp", ".hwpx"}:
        return extract_hwp(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def target_strings(row: dict[str, Any]) -> list[str]:
    summary = row.get("bundle_summary") or {}
    targets: list[str] = []
    targets.extend(summary.get("source_docs") or [])
    targets.extend(summary.get("retrieved_docs_top5") or [])
    return [normalize_text(t) for t in targets if t]


def find_best_raw(target: str, raw_files: list[Path]) -> tuple[int, Path | None]:
    nt = normalize_key(target)
    best_score = 0
    best_path: Path | None = None
    for path in raw_files:
        np = normalize_key(path.name)
        score = 0
        if nt == np:
            score = 100
        elif nt and (nt in np or np in nt):
            score = 80 + min(len(nt), len(np)) // 20
        if score > best_score:
            best_score = score
            best_path = path
    return best_score, best_path


def safe_output_name(path: Path) -> str:
    stem = normalize_text(path.stem)
    stem = re.sub(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ.-]+", "_", stem)
    stem = stem[:120].strip("_") or "document"
    return stem + ".txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-path", type=Path, default=DEFAULT_REVIEW_PATH)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.review_path)
    raw_files = [p for p in args.raw_dir.glob("*") if p.is_file()]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    needed: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = row.get("question_id")
        for target in target_strings(row):
            score, path = find_best_raw(target, raw_files)
            if path and score >= 80:
                record = needed.setdefault(str(path), {"path": path, "questions": set(), "targets": set()})
                record["questions"].add(qid)
                record["targets"].add(target)

    manifest: list[dict[str, Any]] = []
    for index, record in enumerate(needed.values(), 1):
        path: Path = record["path"]
        output_path = args.output_dir / safe_output_name(path)
        status = "ok"
        error = ""
        char_count = 0
        try:
            text = extract_text(path)
            char_count = len(text)
            output_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            status = "error"
            error = repr(exc)
            output_path = Path("")
        manifest.append(
            {
                "index": index,
                "source_path": str(path),
                "output_path": str(output_path) if output_path else "",
                "status": status,
                "error": error,
                "char_count": char_count,
                "questions": sorted(record["questions"]),
                "targets": sorted(record["targets"]),
            }
        )
        print(f"[{index}/{len(needed)}] {status} chars={char_count} {path.name[:80]}")

    manifest_path = args.output_dir.parent / "raw_text_extraction_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] manifest -> {manifest_path}")
    print(f"[OK] success {sum(1 for item in manifest if item['status'] == 'ok')} / {len(manifest)}")


if __name__ == "__main__":
    main()
