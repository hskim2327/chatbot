import ast
import hashlib
import json
from typing import Any


SKIP_CHUNK = object()


def load_chunks_jsonl(path: str) -> list[dict[str, Any]]:
    chunks = []

    with open(path, "r", encoding="utf-8") as f:
        first_char = f.read(1)
        f.seek(0)
        if first_char == "[":
            items = json.load(f)
        else:
            items = [json.loads(line) for line in f if line.strip()]

    for item in items:
        chunk = normalize_chunk(item)
        if chunk is SKIP_CHUNK:
            continue
        chunks.append(chunk)

    return chunks


def normalize_chunk(item: dict[str, Any]) -> dict[str, Any] | object:
    if is_normalized_chunk(item):
        return item
    if "ChunkContent" in item:
        return normalize_rag_database_chunk(item)
    if is_shared_p4_chunk(item) and should_skip_shared_p4_chunk(item):
        return SKIP_CHUNK
    return normalize_chunks_v2_chunk(item)


def is_normalized_chunk(item: dict[str, Any]) -> bool:
    return (
        "chunk_id" in item
        and "doc_id" in item
        and "text" in item
        and isinstance(item.get("metadata"), dict)
    )


def is_shared_p4_chunk(item: dict[str, Any]) -> bool:
    return isinstance(item.get("metadata"), dict) and "source_ref" in item and "embed_enabled" in item


def should_skip_shared_p4_chunk(item: dict[str, Any]) -> bool:
    if item.get("embed_enabled") is not True:
        return True
    if item.get("chunk_type") == "toc":
        return True
    return not str(item.get("content") or "").strip()


def normalize_chunks_v2_chunk(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    chunk_type = item.get("chunk_type") or metadata.get("chunk_type")

    return {
        "chunk_id": item["chunk_id"],
        "doc_id": item["doc_id"],
        "text": item["content"],
        "metadata": {
            "source_file": item.get("source_file") or metadata.get("source_file"),
            "project_name": item.get("project_name") or metadata.get("project_name"),
            "issuer": item.get("issuer") or metadata.get("issuer"),
            "budget": item.get("metadata_budget") or metadata.get("budget") or metadata.get("final_budget"),
            "section_path": item.get("section_path") or metadata.get("section_path"),
            "section_type": item.get("section_type") or metadata.get("section_type"),
            "chunk_type": chunk_type,
            "dates": item.get("dates") or metadata.get("dates"),
            "amounts": item.get("amounts") or metadata.get("amounts"),
            "exact_terms": item.get("exact_terms") or metadata.get("exact_terms"),
            "doc_key": item.get("doc_key") or metadata.get("doc_key"),
            "source_format": item.get("source_format") or metadata.get("source_format"),
            "file_type": item.get("file_type") or metadata.get("file_type"),
            "source_store_id": extract_source_store_id(item),
        },
    }


def normalize_rag_database_chunk(item: dict[str, Any]) -> dict[str, Any]:
    source_file = clean_empty_value(item.get("FileName")) or ""
    issuer = clean_empty_value(item.get("발주기관")) or infer_issuer_from_filename(source_file)
    project_name = clean_empty_value(item.get("사업명")) or infer_project_name_from_filename(source_file)
    budget = clean_empty_value(item.get("사업금액"))
    published_at = clean_empty_value(item.get("나라장터_공고일"))
    bid_deadline = clean_empty_value(item.get("나라장터_마감일"))
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
            "notice_id": clean_empty_value(item.get("공고번호")),
            "file_type": clean_empty_value(item.get("Extension")),
            "project_type": clean_empty_value(item.get("사업유형")),
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


def extract_source_store_id(item: dict[str, Any]) -> str | None:
    source_ref = item.get("source_ref")
    if isinstance(source_ref, dict):
        return source_ref.get("source_store_id")
    return None


def clean_empty_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().casefold() in {"", "none", "null", "nan"}:
        return None
    return value


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
    value = clean_empty_value(value)
    if value is None:
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
