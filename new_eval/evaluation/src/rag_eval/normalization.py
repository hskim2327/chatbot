"""eval/prediction 필드 파싱과 문서명 정규화를 담당한다."""

from __future__ import annotations

import ast
import json
import math
import re
import unicodedata
from typing import Any

import pandas as pd

from .config import OFFICIAL_TOP_K


def parse_structured_cell(value: Any, default: Any) -> Any:
    """CSV 셀에 문자열로 들어 있는 list/dict 값을 안전하게 파싱한다."""

    if pd.isna(value):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except Exception:
            continue
    return default


def normalize_doc_id(value: Any) -> str:
    """문서명을 비교할 수 있도록 유니코드와 공백을 정리한다."""

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def parse_doc_list(value: Any) -> list[str]:
    """ground_truth_docs 값을 문서명 list로 변환한다."""

    parsed = parse_structured_cell(value, [])
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    docs: list[str] = []
    for item in parsed:
        if isinstance(item, dict):
            raw = item.get("filename") or item.get("file_name") or item.get("doc_id") or item.get("document_id")
        else:
            raw = item
        normalized = normalize_doc_id(raw)
        if normalized:
            docs.append(normalized)
    return docs


def context_document_id(context: dict[str, Any]) -> str:
    """검색 context에서 filename을 우선 사용하고 없을 때 doc_id를 사용한다."""

    return normalize_doc_id(context.get("filename") or context.get("doc_id"))


def context_rank(context: dict[str, Any]) -> tuple[float, int]:
    """rank 정렬을 위해 숫자 rank를 우선하고, 없는 값은 뒤로 보낸다."""

    raw_rank = context.get("rank")
    try:
        return float(raw_rank), 0
    except (TypeError, ValueError):
        return float("inf"), 1


def extract_top_unique_documents(retrieved_contexts: Any, top_k: int = OFFICIAL_TOP_K) -> list[str]:
    """rank 순으로 정렬한 뒤 문서 기준으로 중복 제거한 top-k 문서명을 만든다."""

    if not isinstance(retrieved_contexts, list):
        return []

    sorted_contexts = sorted(
        [context for context in retrieved_contexts if isinstance(context, dict)],
        key=context_rank,
    )
    seen: set[str] = set()
    docs: list[str] = []
    for context in sorted_contexts:
        doc_id = context_document_id(context)
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        docs.append(doc_id)
        if len(docs) >= top_k:
            break
    return docs


def retrieved_context_texts(retrieved_contexts: Any) -> list[str]:
    """RAGAS 입력에 사용할 context text를 rank 순서대로 추출한다."""

    if not isinstance(retrieved_contexts, list):
        return []
    sorted_contexts = sorted(
        [context for context in retrieved_contexts if isinstance(context, dict)],
        key=context_rank,
    )
    texts: list[str] = []
    for context in sorted_contexts:
        text = context.get("text")
        if text is not None and str(text).strip():
            texts.append(str(text))
    return texts

