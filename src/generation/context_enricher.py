from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .context_builder import (
    BUDGET_KEYWORDS,
    DATE_KEYWORDS,
    QUALIFICATION_KEYWORDS,
    SUBMISSION_KEYWORDS,
    classify_question,
)

MONEY_OR_NUMBER = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:원|천원|만원|억원|백만원|%|개월|년|월|일)?")


def load_chunks_by_doc(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    chunk_path = Path(path)
    if not chunk_path.exists():
        return {}
    data = json.loads(chunk_path.read_text(encoding="utf-8"))
    chunks_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in data:
        doc_id = item.get("doc_id")
        if doc_id:
            chunks_by_doc[str(doc_id)].append(item)
    return dict(chunks_by_doc)


def enrich_retrieved_contexts(
    question: str,
    retrieved_contexts: list[dict[str, Any]],
    chunks_by_doc: dict[str, list[dict[str, Any]]],
    max_extra_contexts: int = 5,
    max_extra_per_doc: int = 2,
) -> list[dict[str, Any]]:
    if not chunks_by_doc or max_extra_contexts <= 0 or max_extra_per_doc <= 0:
        return retrieved_contexts

    question_type = classify_question(question)
    seen_chunk_ids = {context.get("chunk_id") for context in retrieved_contexts if context.get("chunk_id")}
    doc_ids = _unique_doc_ids(retrieved_contexts)

    candidates = []
    for doc_order, doc_id in enumerate(doc_ids):
        for chunk in chunks_by_doc.get(doc_id, []):
            chunk_id = chunk.get("chunk_id")
            if chunk_id in seen_chunk_ids:
                continue
            score = _score_chunk(question, question_type, chunk)
            if score <= 0:
                continue
            candidates.append((score, -doc_order, chunk))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    per_doc_count: dict[str, int] = defaultdict(int)
    extras = []
    for score, _, chunk in candidates:
        doc_id = str(chunk.get("doc_id") or "")
        if per_doc_count[doc_id] >= max_extra_per_doc:
            continue
        extras.append(_to_context(chunk, score))
        per_doc_count[doc_id] += 1
        if len(extras) >= max_extra_contexts:
            break

    return retrieved_contexts + extras


def _score_chunk(question: str, question_type: str, chunk: dict[str, Any]) -> float:
    metadata = chunk.get("metadata") or {}
    text = str(chunk.get("text") or "")
    haystack = " ".join(
        [
            text,
            str(metadata.get("section_path") or ""),
            str(metadata.get("section_type") or ""),
            str(metadata.get("chunk_type") or ""),
        ]
    )

    keywords = _keywords_for_type(question_type)
    score = 0.0
    if metadata.get("chunk_type") == "fact_candidates":
        score += 4.0
    if metadata.get("section_type") == "핵심 후보 정보":
        score += 3.0
    for keyword in keywords:
        if keyword and keyword in haystack:
            score += 1.0
    for term in _question_terms(question):
        if term in haystack:
            score += 0.25
    if question_type in {"budget", "date_or_period"} and MONEY_OR_NUMBER.search(text):
        score += 1.0
    return score


def _keywords_for_type(question_type: str) -> tuple[str, ...]:
    if question_type == "budget":
        return BUDGET_KEYWORDS + ("사업금액", "배정예산", "KRW")
    if question_type == "submission_documents":
        return SUBMISSION_KEYWORDS + ("제출", "구비", "첨부", "서식")
    if question_type == "date_or_period":
        return DATE_KEYWORDS + ("사업기간", "용역기간", "입찰", "개찰")
    if question_type == "qualification":
        return QUALIFICATION_KEYWORDS + ("공동수급", "제한경쟁", "실적")
    return tuple(_question_terms(question_type))


def _to_context(chunk: dict[str, Any], enrichment_score: float) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    metadata["generation_context_source"] = "sidecar_enrichment"
    return {
        "rank": None,
        "filename": metadata.get("source_file"),
        "doc_id": chunk.get("doc_id"),
        "chunk_id": chunk.get("chunk_id"),
        "score": None,
        "text": chunk.get("text") or "",
        "metadata": metadata,
        "generation_context_source": "sidecar_enrichment",
        "generation_enrichment_score": enrichment_score,
    }


def _unique_doc_ids(retrieved_contexts: list[dict[str, Any]]) -> list[str]:
    result = []
    for context in retrieved_contexts:
        doc_id = context.get("doc_id")
        if doc_id and doc_id not in result:
            result.append(str(doc_id))
    return result


def _question_terms(question: str) -> list[str]:
    stopwords = {"무엇", "얼마", "어떤", "알려", "인가", "입니까", "해당", "사업", "용역"}
    terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", question or "")
    return [term for term in terms if term not in stopwords][:10]
