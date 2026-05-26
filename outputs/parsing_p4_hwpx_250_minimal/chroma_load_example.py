"""Chroma load example for P4 250 minimal corpus.

Default mapping:
- ids       <- chunk_id
- documents <- content
- metadatas <- metadata

Keep Chroma DB outside Google Drive when running on Colab.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer
from tqdm.auto import tqdm


def scalarize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Keep Chroma metadata simple and filter-friendly."""
    clean: dict[str, str | int | float | bool | None] = {}
    for key, value in (metadata or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = " | ".join(str(v) for v in value[:20])
        else:
            clean[key] = json.dumps(value, ensure_ascii=False)[:1000]
    return clean


def iter_chroma_records(chunks_path: Path):
    seen_ids = set()
    with chunks_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("embed_enabled") is not True:
                continue
            if row.get("chunk_type") == "toc":
                continue
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            chunk_id = str(row.get("chunk_id", "")).strip()
            if not chunk_id:
                raise ValueError(f"Missing chunk_id at line {line_no}")
            if chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk_id: {chunk_id}")
            seen_ids.add(chunk_id)
            metadata = scalarize_metadata(row.get("metadata", {}))
            metadata.setdefault("chunk_id", chunk_id)
            metadata.setdefault("source_file", row.get("source_file", ""))
            metadata.setdefault("chunk_type", row.get("chunk_type", ""))
            source_ref = row.get("source_ref", {}) or {}
            if isinstance(source_ref, dict) and source_ref.get("source_store_id"):
                metadata.setdefault("source_store_id", source_ref.get("source_store_id"))
            yield chunk_id, content, metadata


def batched(items, batch_size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def main():
    parser = argparse.ArgumentParser()
    # 팀원별로 다르게 설정해야 하는 값입니다.
    # 본인 Google Drive, GCP VM, 로컬 PC에 있는 chunks_v2_250.jsonl 경로로 바꿔주세요.
    parser.add_argument("--chunks", required=True, help="Path to chunks_v2_250.jsonl")
    parser.add_argument(
        "--chroma-path",
        required=True,
        help="Local Chroma DB path. Prefer /content/... on Colab, not Google Drive.",
    )

    # 팀원별로 다르게 설정할 수 있는 값입니다.
    # 같은 corpus라도 임베딩 모델이나 검색 조건이 다르면 collection 이름을 다르게 두는 것이 안전합니다.
    parser.add_argument("--collection", default="rfp_p4_250_v2_koe5")

    # 팀원별로 다르게 설정할 수 있는 값입니다.
    # 기본값은 KoE5입니다. BGE-M3 등 다른 모델을 쓰면 반드시 collection 이름도 같이 바꿔주세요.
    parser.add_argument("--model", default="nlpai-lab/KoE5")

    # 실행 환경에 맞게 바꿔주세요.
    # Colab/GCP L4 GPU: cuda
    # 로컬 CPU만 사용: cpu
    # Mac M-series: mps 가능 여부 확인 후 사용
    parser.add_argument("--device", default="cuda")

    # GPU 메모리나 런타임 상황에 맞게 조절하세요.
    # OOM이 나면 128 또는 64로 줄이고, 여유가 있으면 256~512를 사용할 수 있습니다.
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        raise FileNotFoundError(chunks_path)

    chroma_path = Path(args.chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    print("chunks:", chunks_path)
    print("chroma_path:", chroma_path)
    print("collection:", args.collection)
    print("model:", args.model)
    print("device:", args.device)

    model = SentenceTransformer(args.model, device=args.device)
    client = chromadb.PersistentClient(path=str(chroma_path))

    try:
        client.delete_collection(args.collection)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=args.collection)

    total = 0
    records = iter_chroma_records(chunks_path)
    for batch in tqdm(batched(records, args.batch_size), desc="embed+chroma add"):
        ids = [x[0] for x in batch]
        documents = [x[1] for x in batch]
        metadatas = [x[2] for x in batch]
        embeddings = model.encode(
            ["passage: " + doc for doc in documents],
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        # 선생님이 설명해주신 ChromaDB 매핑이 적용되는 부분입니다.
        # ids       <- chunk_id
        # documents <- content
        # metadatas <- metadata
        # embeddings는 KoE5로 직접 계산한 벡터입니다.
        collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        total += len(batch)

    print("collection_count:", collection.count())
    print("added_records:", total)

    query = "\uc81c\uc548\uc11c \uc81c\ucd9c \ub9c8\uac10\uc77c\uacfc \uc81c\ucd9c \ubc29\ubc95\uc740 \ubb34\uc5c7\uc778\uac00\uc694?"
    query_embedding = model.encode(["query: " + query], normalize_embeddings=True).tolist()
    result = collection.query(query_embeddings=query_embedding, n_results=3)
    print("\nSMOKE TEST QUERY:", query)
    for rank, (doc, meta) in enumerate(zip(result.get("documents", [[]])[0], result.get("metadatas", [[]])[0]), start=1):
        print("-" * 80)
        print("rank:", rank)
        print("source_file:", meta.get("source_file"))
        print("chunk_type:", meta.get("chunk_type"))
        print("chunk_id:", meta.get("chunk_id"))
        print(str(doc)[:500].replace("\n", " "))


if __name__ == "__main__":
    main()
