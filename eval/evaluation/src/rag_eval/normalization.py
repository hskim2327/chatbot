"""eval/prediction 필드 파싱과 문서명 정규화를 담당한다."""

from __future__ import annotations

import ast
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
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


def doc_match_key(value: Any) -> str:
    """문서명 비교용 key를 만든다. 표기 흔들림은 줄이고 원문 출력은 보존한다."""

    text = normalize_doc_id(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.replace("㈜", "(주)")
    text = text.replace("주식회사", "주")
    text = text.replace("(주)", "주")
    text = text.replace("（주）", "주")
    text = re.sub(r"\.(hwp|hwpx|pdf|docx?|xlsx?)$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def same_doc_prefix(left: Any, right: Any) -> bool:
    """기관/출처 prefix가 있는 파일명끼리는 같은 prefix일 때만 fuzzy match를 허용한다."""

    left_text = normalize_doc_id(left)
    right_text = normalize_doc_id(right)
    if "_" not in left_text or "_" not in right_text:
        return True
    return doc_match_key(left_text.split("_", 1)[0]) == doc_match_key(right_text.split("_", 1)[0])


def documents_match(expected: Any, actual: Any) -> bool:
    """문서명이 같은지 판단한다. 정확 매칭을 우선하고, 긴 파일명의 1~2글자 표기 오류만 엄격하게 허용한다."""

    expected_key = doc_match_key(expected)
    actual_key = doc_match_key(actual)
    if not expected_key or not actual_key:
        return False
    if expected_key == actual_key:
        return True
    if min(len(expected_key), len(actual_key)) < 30:
        return False
    if not same_doc_prefix(expected, actual):
        return False
    return SequenceMatcher(None, expected_key, actual_key).ratio() >= 0.98


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

