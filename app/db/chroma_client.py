import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
CHROMA_DB_PATH = Path(os.getenv("CHROMA_DB_PATH", "./ingest/KuRe"))
if not CHROMA_DB_PATH.is_absolute():
    CHROMA_DB_PATH = ROOT / CHROMA_DB_PATH

COLLECTION_NAME = os.getenv("COLLECTION_NAME", "new_125_kurev1_v2")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nlpai-lab/KURE-v1")


def repair_mojibake(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except Exception:
        return value
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in repaired)
    looks_broken = any(token in value for token in ("\u00ec", "\u00ed", "\u00ea", "\u00eb", "\u00c2", "\u00c3"))
    return repaired if has_hangul and looks_broken else value


def mojibake_alias(value: str) -> str:
    try:
        return value.encode("utf-8").decode("latin1")
    except Exception:
        return value


def _sqlite_path() -> Path:
    return CHROMA_DB_PATH / "chroma.sqlite3"


def _metadata_value(row: sqlite3.Row) -> Any:
    for key in ("string_value", "int_value", "float_value", "bool_value"):
        if key in row.keys() and row[key] is not None:
            return repair_mojibake(row[key])
    return None


@lru_cache(maxsize=1)
def get_all_issuers() -> list[str]:
    db_path = _sqlite_path()
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT DISTINCT string_value
            FROM embedding_metadata
            WHERE key = 'issuer'
              AND string_value IS NOT NULL
              AND TRIM(string_value) != ''
            """
        ).fetchall()
    finally:
        con.close()
    return sorted({repair_mojibake(row["string_value"]).strip() for row in rows if row["string_value"]})


@lru_cache(maxsize=1)
def get_all_records() -> list[dict[str, Any]]:
    db_path = _sqlite_path()
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT
                e.id AS row_id,
                e.embedding_id AS embedding_id,
                m.key AS key,
                m.string_value AS string_value,
                m.int_value AS int_value,
                m.float_value AS float_value,
                m.bool_value AS bool_value
            FROM embeddings e
            JOIN embedding_metadata m ON m.id = e.id
            """
        ).fetchall()
    finally:
        con.close()

    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(
            int(row["row_id"]),
            {"chunk_id": repair_mojibake(row["embedding_id"]), "text": "", "metadata": {}},
        )
        key = row["key"]
        value = _metadata_value(row)
        if key == "chroma:document":
            item["text"] = repair_mojibake(value or "")
        elif key:
            item["metadata"][key] = value

    records = []
    for item in grouped.values():
        meta = {key: repair_mojibake(value) for key, value in (item.get("metadata") or {}).items()}
        records.append(
            {
                "chunk_id": meta.get("chunk_id") or item.get("chunk_id"),
                "text": repair_mojibake(item.get("text") or meta.get("content") or ""),
                "metadata": meta,
            }
        )
    return records


@lru_cache(maxsize=1)
def _collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return client.get_collection(COLLECTION_NAME)


@lru_cache(maxsize=1)
def _embed_model():
    return SentenceTransformer(EMBED_MODEL)


def _where_for_issuers(issuers: list[str]) -> dict[str, Any] | None:
    aliases: list[str] = []
    for issuer in issuers:
        issuer = issuer.strip()
        for candidate in (issuer, mojibake_alias(issuer), repair_mojibake(issuer)):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
    if not aliases:
        return None
    return {"issuer": aliases[0]} if len(aliases) == 1 else {"issuer": {"$in": aliases}}


def dense_search(question: str, issuers: list[str], top_k: int = 50) -> list[dict[str, Any]]:
    try:
        model = _embed_model()
        emb = model.encode([question], normalize_embeddings=True)[0].astype("float32").tolist()
        kwargs: dict[str, Any] = {
            "query_embeddings": [emb],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        where = _where_for_issuers(issuers)
        if where:
            kwargs["where"] = where
        result = _collection().query(**kwargs)
    except Exception:
        return []

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    rows = []
    for i, chunk_id in enumerate(ids):
        distance = distances[i] if i < len(distances) else None
        rows.append(
            {
                "rank": i + 1,
                "chunk_id": chunk_id,
                "text": repair_mojibake(docs[i] if i < len(docs) else ""),
                "metadata": {k: repair_mojibake(v) for k, v in (metas[i] if i < len(metas) and metas[i] else {}).items()},
                "distance": distance,
                "similarity": 1 - distance if distance is not None else 0,
                "retriever": "dense",
            }
        )
    return rows


def records_for_issuers(issuers: list[str]) -> list[dict[str, Any]]:
    allowed = {issuer.strip() for issuer in issuers if issuer.strip()}
    if not allowed:
        return []
    return [r for r in get_all_records() if (r.get("metadata") or {}).get("issuer") in allowed]
