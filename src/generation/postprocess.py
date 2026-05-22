from __future__ import annotations

import re
from typing import Any


NUMBER_OR_DATE_PATTERN = re.compile(
    r"[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:원|천원|만원|억원|백만원|%|일|개월|년|월|시|분)?"
)
DOC_EXTENSION_PATTERN = re.compile(r"[^\s:;]+\.(?:hwp|hwpx|pdf|docx?|xlsx?)", re.IGNORECASE)
UNCERTAIN_MARKERS = ("확인할 수 없습니다", "문서에서 확인", "정보가 없습니다", "알 수 없습니다")


def validate_generation_answer(answer: str, generation_input: Any) -> dict[str, Any]:
    answer = str(answer or "")
    context_text = str(getattr(generation_input, "context_text", "") or "")
    context_records = getattr(generation_input, "context_records", []) or []
    field_candidates = getattr(generation_input, "field_candidates", {}) or {}

    numeric_tokens = _unique(NUMBER_OR_DATE_PATTERN.findall(answer))
    unsupported_numeric_tokens = [token for token in numeric_tokens if token and token not in context_text]

    source_files = [str(record.get("filename") or "") for record in context_records if record.get("filename")]
    mentioned_docs = _unique(DOC_EXTENSION_PATTERN.findall(answer))
    unsupported_docs = [doc for doc in mentioned_docs if not any(_doc_matches(doc, source) for source in source_files)]

    has_citation = any(source and source in answer for source in source_files) or bool(mentioned_docs)
    says_unknown = any(marker in answer for marker in UNCERTAIN_MARKERS)
    has_field_candidates = any(values for values in field_candidates.values())

    warnings = []
    if unsupported_numeric_tokens:
        warnings.append("answer_has_numbers_or_dates_not_found_in_context")
    if unsupported_docs:
        warnings.append("answer_mentions_doc_not_in_retrieved_contexts")
    if not has_citation:
        warnings.append("missing_source_filename_citation")
    if says_unknown and has_field_candidates:
        warnings.append("answer_says_unknown_despite_field_candidates")
    if not answer.strip():
        warnings.append("empty_answer")

    confidence = "high"
    if unsupported_numeric_tokens or unsupported_docs:
        confidence = "low"
    elif warnings:
        confidence = "medium"

    return {
        "confidence": confidence,
        "warnings": warnings,
        "numeric_tokens": numeric_tokens,
        "unsupported_numeric_tokens": unsupported_numeric_tokens,
        "mentioned_docs": mentioned_docs,
        "unsupported_docs": unsupported_docs,
        "has_citation": has_citation,
        "says_unknown": says_unknown,
    }


def dedupe_repeated_lines(answer: str) -> str:
    seen = set()
    lines = []
    for line in str(answer or "").splitlines():
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def _unique(values: list[str]) -> list[str]:
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _doc_matches(mentioned: str, source: str) -> bool:
    mentioned_key = _normalize_doc(mentioned)
    source_key = _normalize_doc(source)
    return mentioned_key in source_key or source_key in mentioned_key


def _normalize_doc(value: str) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)
