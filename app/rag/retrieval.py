import math
from collections import Counter, defaultdict
from typing import Any

from app.db.chroma_client import dense_search, records_for_issuers
from app.rag.config import DENSE_K, QUESTION_FACT_TYPES, SPARSE_K, norm_text
from app.rag.rerank import infer_question_type


def _tokens(text: str) -> list[str]:
    base = norm_text(text)
    compact = base.replace(" ", "")
    tokens = [tok for tok in base.split() if len(tok) >= 2]
    for n in (2, 3):
        tokens.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
    return tokens


def sparse_search(question: str, issuers: list[str], top_k: int = SPARSE_K) -> list[dict[str, Any]]:
    q_counts = Counter(_tokens(question))
    rows = []
    for record in records_for_issuers(issuers):
        counts = Counter(_tokens(record.get("text", "")))
        overlap = sum(min(count, counts.get(tok, 0)) for tok, count in q_counts.items())
        if overlap <= 0:
            continue
        item = dict(record)
        item["sparse_score"] = overlap / math.sqrt(max(1, len(counts)))
        item["retriever"] = "sparse"
        rows.append(item)
    rows.sort(key=lambda x: x["sparse_score"], reverse=True)
    for i, row in enumerate(rows[:top_k], 1):
        row["rank"] = i
    return rows[:top_k]


def rrf_merge(lists: list[list[dict[str, Any]]], k: int = 60) -> list[dict[str, Any]]:
    scores: dict[str, float] = defaultdict(float)
    items: dict[str, dict[str, Any]] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    for rows in lists:
        for rank, row in enumerate(rows, 1):
            cid = row.get("chunk_id")
            if not cid:
                continue
            scores[cid] += 1 / (k + rank)
            items.setdefault(cid, dict(row))
            sources[cid].add(row.get("retriever", "unknown"))
    merged = []
    for cid, item in items.items():
        item = dict(item)
        item["rrf_score"] = scores[cid]
        item["retrievers"] = ",".join(sorted(sources[cid]))
        merged.append(item)
    return sorted(merged, key=lambda x: x["rrf_score"], reverse=True)


def backfill(question: str, issuers: list[str], seeds: list[dict[str, Any]], per_doc: int = 2) -> list[dict[str, Any]]:
    qtype = infer_question_type(question)
    needed = QUESTION_FACT_TYPES.get(qtype, QUESTION_FACT_TYPES["general"])
    doc_ids = []
    for row in seeds[:10]:
        meta = row.get("metadata") or {}
        doc_id = meta.get("canonical_doc_id") or meta.get("doc_id")
        if doc_id and doc_id not in doc_ids:
            doc_ids.append(doc_id)
        if len(doc_ids) >= 5:
            break
    counts = {doc_id: 0 for doc_id in doc_ids}
    out = []
    for record in records_for_issuers(issuers):
        meta = record.get("metadata") or {}
        doc_id = meta.get("canonical_doc_id") or meta.get("doc_id")
        if doc_id not in counts or counts[doc_id] >= per_doc:
            continue
        if meta.get("fact_type") not in needed:
            continue
        item = dict(record)
        item["retriever"] = "ngram_doc_backfill"
        item["rank"] = len(out) + 1
        counts[doc_id] += 1
        out.append(item)
    return out


def hybrid_retrieve(question: str, issuers: list[str]) -> dict[str, list[dict[str, Any]]]:
    dense = dense_search(question, issuers, DENSE_K)
    sparse = sparse_search(question, issuers, SPARSE_K)
    initial = rrf_merge([dense, sparse])
    fills = backfill(question, issuers, initial)
    merged = rrf_merge([dense, sparse, fills])
    return {"dense": dense, "sparse": sparse, "backfill": fills, "merged": merged}
