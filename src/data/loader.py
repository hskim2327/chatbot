import ast
import hashlib
import json
from typing import Any


def load_chunks_jsonl(path: str) -> list[dict[str, Any]]:
    chunks = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            chunks.append(normalize_chunk(item))

    return chunks


def normalize_chunk(item: dict[str, Any]) -> dict[str, Any]:
    if "ChunkContent" in item:
        return normalize_rag_database_chunk(item)
    return normalize_chunks_v2_chunk(item)


def normalize_chunks_v2_chunk(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": item["chunk_id"],
        "doc_id": item["doc_id"],
        "text": item["content"],
        "metadata": {
            "source_file": item.get("source_file"),
            "project_name": item.get("project_name"),
            "issuer": item.get("issuer"),
            "budget": item.get("metadata_budget"),
            "section_path": item.get("section_path"),
            "section_type": item.get("section_type"),
            "chunk_type": item.get("chunk_type"),
            "dates": item.get("dates"),
            "amounts": item.get("amounts"),
            "exact_terms": item.get("exact_terms"),
        },
    }


def normalize_rag_database_chunk(item: dict[str, Any]) -> dict[str, Any]:
    source_file = item.get("FileName") or ""
    issuer = item.get("발주기관") or infer_issuer_from_filename(source_file)
    project_name = item.get("사업명") or infer_project_name_from_filename(source_file)
    budget = item.get("사업금액")
    published_at = item.get("나라장터_공고일")
    bid_deadline = item.get("나라장터_마감일")
    keywords = parse_keywords(item.get("핵심키워드"))

    return {
        "chunk_id": item["ChunkID"],
        "doc_id": make_doc_id(source_file),
        "text": item["ChunkContent"],
        "metadata": {
            "source_file": source_file,
            "project_name": project_name,
            "issuer": issuer,
            "budget": budget,
            "notice_id": item.get("공고번호"),
            "file_type": item.get("Extension"),
            "project_type": item.get("사업유형"),
            "keywords": keywords,
            "published_at": published_at,
            "bid_deadline": bid_deadline,
            "section_path": None,
            "section_type": None,
            "chunk_type": "rag_database",
            "dates": [value for value in (published_at, bid_deadline) if value],
            "amounts": [budget] if budget else [],
            "exact_terms": keywords,
        },
    }


def infer_issuer_from_filename(source_file: str) -> str:
    filename = source_file.rsplit("/", 1)[-1]
    if "_" not in filename:
        return ""
    return filename.split("_", 1)[0].strip()


def infer_project_name_from_filename(source_file: str) -> str:
    filename = source_file.rsplit("/", 1)[-1]
    if "_" in filename:
        filename = filename.split("_", 1)[1]
    for extension in (".pdf", ".hwp", ".hwpx", ".docx", ".xlsx"):
        if filename.casefold().endswith(extension):
            filename = filename[: -len(extension)]
            break
    return filename.strip()


def make_doc_id(source_file: str) -> str:
    digest = hashlib.sha1(source_file.encode("utf-8")).hexdigest()[:10]
    return f"doc_{digest}"


def parse_keywords(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = ast.literal_eval(str(value))
    except (SyntaxError, ValueError):
        return [str(value)]
    if isinstance(parsed, list):
        return parsed
    return [parsed]
