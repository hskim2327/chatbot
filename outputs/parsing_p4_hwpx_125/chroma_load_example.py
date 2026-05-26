"""P4 HWPX 125 corpus Chroma load example.

이 파일은 `chunks_v2_125.jsonl`을 Chroma에 적재하는 독립 실행 예시입니다.

Chroma mapping:
- ids       <- chunk_id
- documents <- content
- metadatas <- metadata

Colab 권장 실행 예시:
    !python outputs/parsing_p4_hwpx_125/chroma_load_example.py \
        --chunks outputs/parsing_p4_hwpx_125/chunks_v2_125.jsonl \
        --chroma-path /content/chroma_p4_hwpx_125 \
        --device cuda \
        --force-rebuild

GCP VM 권장 실행 예시:
    python outputs/parsing_p4_hwpx_125/chroma_load_example.py \
        --chunks /path/to/outputs/parsing_p4_hwpx_125/chunks_v2_125.jsonl \
        --chroma-path /mnt/disks/local-ssd/chroma_p4_hwpx_125 \
        --device cuda \
        --force-rebuild

주의:
- Colab에서는 Chroma DB를 Google Drive 안에 직접 만들지 않는 것이 안전합니다.
  `/content/...`처럼 런타임 로컬 디스크를 사용하세요.
- GCP에서는 가능하면 VM 로컬 SSD, Persistent Disk, 또는 빠른 로컬 경로를 사용하세요.
- `source_store_125.jsonl`은 긴 원문/표 근거 조회용입니다. Chroma metadata에 넣지 않습니다.
"""

from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# Colab에서 자주 발생한 충돌을 피하기 위해 import 전에 패키지 상태를 점검합니다.
# 특히 아래 두 오류를 방지하는 것이 목적입니다.
# - chromadb import 중 opentelemetry 내부 심볼 불일치
# - sentence-transformers/transformers import 중 tokenizers 버전 불일치
PACKAGE_SPECS = [
    "chromadb",
    "sentence-transformers",
    "transformers>=4.56.0,<5",
    "tokenizers>=0.22.0,<0.23.1",
    "tqdm",
    "opentelemetry-api",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp-proto-grpc",
    "opentelemetry-exporter-otlp-proto-http",
    "opentelemetry-proto",
]

MODULE_TO_PIP = {
    "chromadb": "chromadb",
    "sentence_transformers": "sentence-transformers",
    "tqdm": "tqdm",
}

IMPORT_TEST_CODE = "import chromadb; import sentence_transformers; import tqdm; print('import ok')"


def package_version(package_name: str) -> str:
    """Return installed package version, or an empty string when absent."""
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return ""


def version_tuple(version_text: str) -> tuple[int, int, int]:
    """Parse the numeric part of a version string for simple range checks."""
    nums = [int(x) for x in re.findall(r"\d+", version_text)[:3]]
    return tuple((nums + [0, 0, 0])[:3])


def run_import_test() -> tuple[bool, str]:
    """Test heavy imports in a subprocess so a broken import does not poison this process."""
    proc = subprocess.run(
        [sys.executable, "-c", IMPORT_TEST_CODE],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode == 0:
        return True, proc.stdout.strip()
    return False, (proc.stderr or proc.stdout).strip()


def ensure_retrieval_packages(auto_install: bool = True) -> None:
    """Install or upgrade packages only when the current environment is missing/broken.

    Colab 사용자는 보통 이 기본 동작을 그대로 쓰면 됩니다.
    GCP 사용자는 venv/conda 환경을 고정하고 싶다면 `--skip-package-check`를 사용하거나,
    사전에 requirements를 직접 설치한 뒤 실행하세요.
    """
    missing = [pip_name for module_name, pip_name in MODULE_TO_PIP.items() if importlib.util.find_spec(module_name) is None]
    broken: dict[str, str] = {}

    tok_version = package_version("tokenizers")
    if tok_version and not ((0, 22, 0) <= version_tuple(tok_version) < (0, 23, 1)):
        broken["tokenizers"] = f"tokenizers=={tok_version}; expected >=0.22.0,<0.23.1"

    import_ok, import_message = run_import_test()
    if not import_ok:
        broken["import_test"] = import_message

    versions = {
        "chromadb": package_version("chromadb"),
        "sentence-transformers": package_version("sentence-transformers"),
        "transformers": package_version("transformers"),
        "tokenizers": package_version("tokenizers"),
        "opentelemetry-api": package_version("opentelemetry-api"),
        "opentelemetry-sdk": package_version("opentelemetry-sdk"),
    }
    print("missing packages:", missing)
    print("broken imports:", broken)
    print("installed versions:", versions)

    if not missing and not broken:
        print("environment looks ready")
        return

    if not auto_install:
        pip_cmd = " ".join([sys.executable, "-m", "pip", "install", "-U", *PACKAGE_SPECS])
        raise RuntimeError(
            "Retrieval packages are missing or broken. "
            f"Install them manually, then rerun. Suggested command:\n{pip_cmd}"
        )

    print("installing/upgrading retrieval packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-U", *PACKAGE_SPECS])
    print("install complete. Rechecking imports...")

    import_ok, import_message = run_import_test()
    if not import_ok:
        raise RuntimeError(
            "Package install finished, but imports still fail. "
            "In Colab, restart the runtime once and rerun the same command. "
            f"Import error:\n{import_message}"
        )
    print(import_message)


def scalarize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Keep Chroma metadata flat and filter-friendly.

    Chroma metadata에는 긴 list/dict 원문을 넣지 않습니다. 필터링과 출처 확인에 필요한
    스칼라 값만 넣고, 복잡한 값은 짧은 문자열로 접습니다.
    """
    clean: dict[str, str | int | float | bool] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            clean[key] = ""
        elif isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, (str, int, float)):
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = " | ".join(str(v) for v in value[:20])[:1000]
        else:
            clean[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)[:1000]
    return clean


def row_to_chroma_record(row: dict[str, Any], line_no: int) -> tuple[str, str, dict[str, str | int | float | bool]] | None:
    """Convert one JSONL row to Chroma `(id, document, metadata)`.

    `embed_enabled=false`, `toc`, empty content rows are intentionally skipped.
    """
    if row.get("embed_enabled") is not True:
        return None
    if row.get("chunk_type") == "toc":
        return None

    content = str(row.get("content", "")).strip()
    if not content:
        return None

    chunk_id = str(row.get("chunk_id", "")).strip()
    if not chunk_id:
        raise ValueError(f"Missing chunk_id at line {line_no}")

    metadata = scalarize_metadata(row.get("metadata", {}))
    metadata.setdefault("chunk_id", chunk_id)
    metadata.setdefault("source_file", str(row.get("source_file", "")))
    metadata.setdefault("doc_id", str(row.get("doc_id", "")))
    metadata.setdefault("chunk_type", str(row.get("chunk_type", "")))
    metadata.setdefault("fact_type", str(row.get("fact_type", "")))

    source_ref = row.get("source_ref", {}) or {}
    if isinstance(source_ref, dict) and source_ref.get("source_store_id"):
        metadata.setdefault("source_store_id", str(source_ref.get("source_store_id")))

    return chunk_id, content, metadata


def scan_chroma_records(chunks_path: Path, max_records: int | None = None) -> dict[str, Any]:
    """Run a fast sanity scan before expensive embedding starts."""
    seen_ids: set[str] = set()
    chunk_types: Counter[str] = Counter()
    fact_types: Counter[str] = Counter()
    jsonl_rows = 0
    selected_rows = 0
    duplicate_ids = 0

    with chunks_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            jsonl_rows += 1
            row = json.loads(line)
            chunk_types[str(row.get("chunk_type", ""))] += 1
            if row.get("chunk_type") == "fact_candidates":
                fact_types[str(row.get("fact_type", ""))] += 1

            record = row_to_chroma_record(row, line_no)
            if record is None:
                continue
            chunk_id = record[0]
            duplicate_ids += int(chunk_id in seen_ids)
            seen_ids.add(chunk_id)
            selected_rows += 1
            if max_records is not None and selected_rows >= max_records:
                break

    return {
        "jsonl_rows_scanned": jsonl_rows,
        "selected_rows": selected_rows,
        "duplicate_selected_chunk_ids": duplicate_ids,
        "chunk_types": dict(chunk_types),
        "fact_types": dict(fact_types),
    }


def iter_chroma_records(chunks_path: Path, max_records: int | None = None) -> Iterable[tuple[str, str, dict[str, str | int | float | bool]]]:
    """Yield validated Chroma records from the P4 JSONL file."""
    seen_ids: set[str] = set()
    yielded = 0
    with chunks_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            record = row_to_chroma_record(row, line_no)
            if record is None:
                continue
            chunk_id = record[0]
            if chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk_id selected for Chroma: {chunk_id}")
            seen_ids.add(chunk_id)
            yield record
            yielded += 1
            if max_records is not None and yielded >= max_records:
                break


def batched(items: Iterable[Any], batch_size: int) -> Iterable[list[Any]]:
    """Yield fixed-size batches without loading the full corpus into memory."""
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def resolve_device(requested_device: str) -> str:
    """Resolve `auto` to cuda/mps/cpu after package checks are complete."""
    if requested_device != "auto":
        return requested_device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def build_or_reuse_collection(args: argparse.Namespace, expected_count: int):
    """Create a Chroma collection, or reuse it only when the count already matches."""
    import chromadb
    from chromadb.config import Settings

    chroma_path = Path(args.chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(chroma_path),
        settings=Settings(anonymized_telemetry=False),
    )

    collection = None
    existing_count = None
    try:
        collection = client.get_collection(args.collection)
        existing_count = collection.count()
        print("existing collection count:", existing_count)
    except Exception:
        print("no existing collection")

    if args.force_rebuild and collection is not None:
        print("deleting existing collection because --force-rebuild was set:", args.collection)
        client.delete_collection(args.collection)
        collection = None
        existing_count = None

    if collection is not None:
        if existing_count == expected_count:
            print("collection already complete; skip embedding/add")
            return collection, False
        raise RuntimeError(
            "Existing collection count does not match selected chunks. "
            f"existing={existing_count}, expected={expected_count}. "
            "Use --force-rebuild or a different --collection name."
        )

    collection = client.create_collection(
        name=args.collection,
        metadata={
            "hnsw:space": "cosine",
            "corpus": "p4_hwpx_125",
            "embedding_model": args.model,
            "source_chunks": str(args.chunks),
        },
    )
    return collection, True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load P4 HWPX 125 chunks into Chroma with KoE5 embeddings.")
    parser.add_argument("--chunks", required=True, help="Path to chunks_v2_125.jsonl")
    parser.add_argument(
        "--chroma-path",
        required=True,
        help="Local Chroma DB path. In Colab, prefer /content/... instead of Google Drive.",
    )
    parser.add_argument("--collection", default="rfp_p4_125_v2_koe5", help="Chroma collection name")
    parser.add_argument("--model", default="nlpai-lab/KoE5", help="SentenceTransformer embedding model")
    parser.add_argument(
        "--device",
        default="auto",
        help="auto, cuda, cpu, or mps. Colab/GCP GPU users usually use cuda.",
    )
    parser.add_argument("--batch-size", type=int, default=128, help="Chroma add batch size")
    parser.add_argument("--encode-batch-size", type=int, default=64, help="SentenceTransformer encode batch size")
    parser.add_argument("--max-records", type=int, default=None, help="Optional smoke-test limit for selected embed records")
    parser.add_argument("--force-rebuild", action="store_true", help="Delete and rebuild the collection if it already exists")
    parser.add_argument(
        "--skip-package-check",
        action="store_true",
        help="Skip automatic package conflict check/install. Useful for locked GCP environments.",
    )
    parser.add_argument(
        "--no-auto-install",
        action="store_true",
        help="Check packages but do not install automatically when a problem is found.",
    )
    parser.add_argument(
        "--query",
        default="제안서 제출 마감일과 제출 방법은 무엇인가요?",
        help="Smoke-test query after indexing",
    )
    parser.add_argument("--n-results", type=int, default=5, help="Number of smoke-test search results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks_path = Path(args.chunks).expanduser().resolve()
    args.chunks = str(chunks_path)

    if not chunks_path.exists():
        raise FileNotFoundError(chunks_path)
    if args.batch_size <= 0 or args.encode_batch_size <= 0:
        raise ValueError("--batch-size and --encode-batch-size must be positive integers")

    if not args.skip_package_check:
        ensure_retrieval_packages(auto_install=not args.no_auto_install)

    # Heavy imports happen only after the package guard. This order is important for Colab.
    from sentence_transformers import SentenceTransformer
    from tqdm.auto import tqdm

    device = resolve_device(args.device)
    print("chunks:", chunks_path)
    print("chroma_path:", Path(args.chroma_path).expanduser().resolve())
    print("collection:", args.collection)
    print("model:", args.model)
    print("device:", device)
    print("batch_size:", args.batch_size)
    print("encode_batch_size:", args.encode_batch_size)
    print("max_records:", args.max_records)

    scan = scan_chroma_records(chunks_path, args.max_records)
    print("sanity scan:", json.dumps(scan, ensure_ascii=False, indent=2))
    if scan["duplicate_selected_chunk_ids"]:
        raise RuntimeError(f"duplicate selected chunk ids: {scan['duplicate_selected_chunk_ids']}")
    expected_count = int(scan["selected_rows"])
    if expected_count == 0:
        raise RuntimeError("No Chroma records selected. Check embed_enabled/content filters.")

    collection, should_add = build_or_reuse_collection(args, expected_count)
    model = SentenceTransformer(args.model, device=device)

    if should_add:
        records = iter_chroma_records(chunks_path, args.max_records)
        progress = tqdm(total=expected_count, desc="embed + chroma", unit="chunk", dynamic_ncols=True)
        total = 0
        try:
            for batch in batched(records, args.batch_size):
                ids = [x[0] for x in batch]
                documents = [x[1] for x in batch]
                metadatas = [x[2] for x in batch]
                embeddings = model.encode(
                    ["passage: " + doc for doc in documents],
                    batch_size=args.encode_batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).astype("float32").tolist()

                # ChromaDB 매핑이 실제로 적용되는 부분입니다.
                # ids       <- P4 JSONL의 chunk_id
                # documents <- P4 JSONL의 content
                # metadatas <- P4 JSONL의 metadata + 출처 보조 필드
                # embeddings는 KoE5가 content에 대해 계산한 dense vector입니다.
                collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
                total += len(batch)
                progress.update(len(batch))
                progress.set_postfix(count=collection.count(), refresh=True)
        finally:
            progress.close()
        print("added_records:", total)
    else:
        print("added_records: 0")

    final_count = collection.count()
    print("collection_count:", final_count)
    if final_count != expected_count:
        raise RuntimeError(f"collection count mismatch: {final_count} != {expected_count}")

    query_embedding = model.encode(["query: " + args.query], normalize_embeddings=True).astype("float32").tolist()
    result = collection.query(query_embeddings=query_embedding, n_results=args.n_results)
    print("\nSMOKE TEST QUERY:", args.query)
    for rank, (doc, meta) in enumerate(zip(result.get("documents", [[]])[0], result.get("metadatas", [[]])[0]), start=1):
        print("-" * 80)
        print("rank:", rank)
        print("source_file:", meta.get("source_file"))
        print("doc_id:", meta.get("doc_id"))
        print("chunk_type:", meta.get("chunk_type"))
        print("fact_type:", meta.get("fact_type"))
        print("chunk_id:", meta.get("chunk_id"))
        print(str(doc)[:700].replace("\n", " "))


if __name__ == "__main__":
    main()
