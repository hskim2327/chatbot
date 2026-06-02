"""Phase 3 RFP 도메인 특화 deterministic metric을 계산한다."""

from __future__ import annotations

import math
import re
from typing import Any

from .config import OFFICIAL_TOP_K
from .normalization import extract_top_unique_documents, normalize_doc_id


def _safe_text(value: Any) -> str:
    """None/NaN 값을 빈 문자열로 바꿔 비교 가능한 텍스트를 만든다."""

    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _contains(answer: str, value: Any) -> bool:
    """공백 차이를 줄여 단순 포함 여부를 확인한다."""

    haystack = re.sub(r"\s+", "", answer.lower())
    needle = re.sub(r"\s+", "", _safe_text(value).lower())
    return bool(needle and needle in haystack)


def _as_list(value: Any) -> list[Any]:
    """값을 list로 정규화한다."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and not value.strip():
        return []
    return [value]


def _keyword_aliases(keyword: str) -> list[str]:
    """짧은 영어 핵심 필드명을 한국어 답변에서 찾기 위한 최소 alias를 제공한다."""

    aliases = {
        "budget": ["budget", "예산", "금액", "사업비", "총액"],
        "project_budget": ["project_budget", "예산", "금액", "사업비"],
        "deadline": ["deadline", "마감", "기한", "제출일"],
        "submission": ["submission", "제출", "서류", "제안서"],
        "eligibility": ["eligibility", "자격", "참가자격", "입찰자격"],
    }
    return aliases.get(keyword.lower(), [keyword])


def extract_krw_amounts(text: str) -> list[int]:
    """답변 텍스트에서 원화 금액 표현을 찾아 KRW 정수로 정규화한다."""

    amounts: list[int] = []
    source = _safe_text(text)

    unit_pattern = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(억원|억|백만원|만원|천원|원)")
    for match in unit_pattern.finditer(source):
        number = float(match.group(1).replace(",", ""))
        unit = match.group(2)
        multiplier = {
            "억원": 100_000_000,
            "억": 100_000_000,
            "백만원": 1_000_000,
            "만원": 10_000,
            "천원": 1_000,
            "원": 1,
        }[unit]
        amounts.append(int(round(number * multiplier)))

    return amounts


def _amount_matches(actual_amounts: list[int], expected: Any, tolerance_krw: int = 0, tolerance_ratio: float = 0.0) -> bool:
    """추출 금액 중 expected와 허용 오차 안에서 일치하는 값이 있는지 확인한다."""

    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        return False
    allowed = max(int(tolerance_krw or 0), int(abs(expected_int) * float(tolerance_ratio or 0.0)))
    return any(abs(actual - expected_int) <= allowed for actual in actual_amounts)


def compute_budget_numeric_accuracy(answer: str, budget_gold: dict[str, Any]) -> dict[str, Any]:
    """예산/금액 답변의 숫자 정확도를 계산한다."""

    warnings: list[str] = []
    parse_error = ""
    try:
        actual_amounts = extract_krw_amounts(answer)
    except Exception as exc:  # pragma: no cover - 방어용 분기
        actual_amounts = []
        parse_error = str(exc)

    tolerance_krw = int(budget_gold.get("tolerance_krw") or 0)
    tolerance_ratio = float(budget_gold.get("tolerance_ratio") or 0.0)
    items = [item for item in _as_list(budget_gold.get("items")) if isinstance(item, dict)]
    expected_amounts = [item.get("amount_krw") for item in items if item.get("amount_krw") is not None]

    item_match_count = sum(
        1 for amount in expected_amounts if _amount_matches(actual_amounts, amount, tolerance_krw, tolerance_ratio)
    )
    item_total_count = len(expected_amounts)
    item_score = item_match_count / item_total_count if item_total_count else math.nan

    total_krw = budget_gold.get("total_krw")
    total_match: bool | None
    if total_krw is None:
        total_match = None
        accuracy = item_score if not math.isnan(item_score) else math.nan
    else:
        total_match = _amount_matches(actual_amounts, total_krw, tolerance_krw, tolerance_ratio)
        total_score = 1.0 if total_match else 0.0
        accuracy = (item_score + total_score) / 2 if item_total_count else total_score

    excluded = [item for item in _as_list(budget_gold.get("excluded_budget_candidates")) if isinstance(item, dict)]
    excluded_hits = [
        item
        for item in excluded
        if item.get("amount_krw") is not None and _amount_matches(actual_amounts, item.get("amount_krw"), 0, 0.0)
    ]
    if excluded_hits:
        warnings.append("excluded_budget_candidate_mentioned")
        accuracy = min(float(accuracy or 0.0), 0.5)

    if not actual_amounts:
        warnings.append("no_amount_parsed")

    return {
        "budget_numeric_accuracy": accuracy,
        "budget_item_match_count": int(item_match_count),
        "budget_item_total_count": int(item_total_count),
        "budget_total_match": total_match,
        "budget_parse_error": parse_error,
        "budget_warning": "; ".join(warnings),
    }


def _match_required_field(answer: str, field: dict[str, Any]) -> bool:
    """required_field_gold의 단일 field가 답변에 충족되는지 판단한다."""

    match_type = _safe_text(field.get("match_type") or "keyword_coverage")
    expected_values = _as_list(field.get("expected_values"))
    if field.get("expected_value") is not None:
        expected_values.append(field.get("expected_value"))
    expected_keywords = _as_list(field.get("expected_keywords"))

    if match_type in {"exact", "exact_or_alias", "date"}:
        return any(_contains(answer, value) for value in expected_values or expected_keywords)

    if match_type == "numeric_krw":
        amounts = extract_krw_amounts(answer)
        return any(_amount_matches(amounts, value) for value in expected_values)

    candidates = expected_keywords if expected_keywords else expected_values
    if not candidates:
        return False
    min_match_count = int(field.get("min_match_count") or len(candidates))
    matched = sum(1 for value in candidates if _contains(answer, value))
    return matched >= min_match_count


def compute_required_field_accuracy(answer: str, required_field_gold: dict[str, Any]) -> dict[str, Any]:
    """required_field_gold.fields 기준으로 필수 정보 포함률을 계산한다."""

    fields = [field for field in _as_list(required_field_gold.get("fields")) if isinstance(field, dict)]
    total_weight = 0.0
    matched_weight = 0.0
    matched_count = 0
    total_count = 0
    missing: list[str] = []

    for field in fields:
        required = field.get("required", True)
        if required is False:
            continue
        weight = float(field.get("weight") or 1.0)
        field_name = _safe_text(field.get("field_name") or "unknown")
        total_weight += weight
        total_count += 1
        if _match_required_field(answer, field):
            matched_weight += weight
            matched_count += 1
        else:
            missing.append(field_name)

    accuracy = matched_weight / total_weight if total_weight else math.nan
    return {
        "required_field_accuracy": accuracy,
        "required_field_matched_count": int(matched_count),
        "required_field_total_count": int(total_count),
        "required_field_missing_items": missing,
        "submission_documents_coverage": math.nan,
        "eligibility_terms_coverage": math.nan,
        "deadline_match": None,
        "required_field_warning": "" if total_count else "no_required_fields",
    }


def _coverage(answer: str, items: list[Any]) -> float:
    """체크리스트 항목의 단순 포함률을 계산한다."""

    clean_items = [item for item in items if _safe_text(item).strip()]
    if not clean_items:
        return math.nan
    return sum(1 for item in clean_items if _contains(answer, item)) / len(clean_items)


def compute_submission_eligibility_deadline_accuracy(answer: str, gold: dict[str, Any]) -> dict[str, Any]:
    """제출서류/입찰자격/마감일 gold block의 checklist 기반 정확도를 계산한다."""

    submission_cov = _coverage(answer, _as_list(gold.get("submission_documents")))
    eligibility_cov = _coverage(answer, _as_list(gold.get("eligibility_terms")))
    deadline_value = gold.get("deadline")
    deadline_match = None if deadline_value in (None, "") else _contains(answer, deadline_value)

    scores = [score for score in (submission_cov, eligibility_cov) if not math.isnan(score)]
    if deadline_match is not None:
        scores.append(1.0 if deadline_match else 0.0)
    accuracy = sum(scores) / len(scores) if scores else math.nan

    total_count = 0
    matched_count = 0
    missing: list[str] = []
    for label, score in (("submission_documents", submission_cov), ("eligibility_terms", eligibility_cov)):
        if not math.isnan(score):
            total_count += 1
            if score >= 1.0:
                matched_count += 1
            else:
                missing.append(label)
    if deadline_match is not None:
        total_count += 1
        if deadline_match:
            matched_count += 1
        else:
            missing.append("deadline")

    return {
        "required_field_accuracy": accuracy,
        "required_field_matched_count": int(matched_count),
        "required_field_total_count": int(total_count),
        "required_field_missing_items": missing,
        "submission_documents_coverage": submission_cov,
        "eligibility_terms_coverage": eligibility_cov,
        "deadline_match": deadline_match,
        "required_field_warning": "" if total_count else "no_submission_eligibility_deadline_gold",
    }


def compute_unanswerable_refusal_accuracy(answer: str, unanswerable_gold: dict[str, Any]) -> dict[str, Any]:
    """문서에 없는 질문에서 확인 불가 응답과 금지 단정 여부를 평가한다."""

    allowed = _as_list(unanswerable_gold.get("allowed_refusal_phrases"))
    patterns = _as_list(unanswerable_gold.get("forbidden_hallucination_patterns"))
    claim_types = _as_list(unanswerable_gold.get("forbidden_claim_types"))

    refusal_found = any(_contains(answer, phrase) for phrase in allowed)
    forbidden_matches = [pattern for pattern in patterns if _contains(answer, pattern)]
    forbidden_matches.extend([claim for claim in claim_types if _contains(answer, claim)])
    forbidden_found = bool(forbidden_matches)

    if refusal_found and not forbidden_found:
        accuracy = 1.0
    elif refusal_found and forbidden_found:
        accuracy = 0.5
    elif forbidden_found:
        accuracy = 0.0
    else:
        accuracy = 0.5

    return {
        "unanswerable_refusal_accuracy": accuracy,
        "refusal_phrase_found": refusal_found,
        "forbidden_claim_found": forbidden_found,
        "forbidden_claim_matches": forbidden_matches,
        "unanswerable_warning": "" if allowed else "no_allowed_refusal_phrases",
    }


def compute_multi_doc_structure_score(
    answer: str,
    multi_doc_gold: dict[str, Any],
    retrieved_contexts: Any | None = None,
) -> dict[str, Any]:
    """다중 문서 비교 답변의 문서 coverage, 비교축, 출력 구조를 평가한다."""

    compared_docs = [normalize_doc_id(doc) for doc in _as_list(multi_doc_gold.get("compared_docs"))]
    compared_docs = [doc for doc in compared_docs if doc]
    retrieved_docs = set(extract_top_unique_documents(retrieved_contexts or [], top_k=OFFICIAL_TOP_K))
    doc_matches = sum(1 for doc in compared_docs if doc in retrieved_docs or _contains(answer, doc))
    doc_coverage_score = doc_matches / len(compared_docs) if compared_docs else math.nan

    axes = _as_list(multi_doc_gold.get("required_comparison_axes"))
    structures = _as_list(multi_doc_gold.get("required_output_structure"))
    comparison_axis_score = _coverage(answer, axes)
    output_structure_score = _coverage(answer, structures)

    scores = [score for score in (doc_coverage_score, comparison_axis_score, output_structure_score) if not math.isnan(score)]
    final_score = sum(scores) / len(scores) if scores else math.nan
    warning = "" if scores else "no_multi_doc_structure_gold"

    return {
        "multi_doc_structure_score": final_score,
        "doc_coverage_score": doc_coverage_score,
        "comparison_axis_score": comparison_axis_score,
        "output_structure_score": output_structure_score,
        "multi_doc_warning": warning,
    }


def compute_robust_query_consistency_score(
    answer: str,
    robust_gold: dict[str, Any],
    retrieved_contexts: Any | None = None,
) -> dict[str, Any]:
    """오타/구어체 질문이 같은 문서와 핵심 필드를 유지하는지 평가한다."""

    expected_docs = [normalize_doc_id(doc) for doc in _as_list(robust_gold.get("expected_same_source_docs"))]
    expected_docs = [doc for doc in expected_docs if doc]
    retrieved_docs = set(extract_top_unique_documents(retrieved_contexts or [], top_k=OFFICIAL_TOP_K))
    doc_match = bool(expected_docs and any(doc in retrieved_docs for doc in expected_docs))

    key_fields = [_safe_text(field) for field in _as_list(robust_gold.get("expected_same_key_fields"))]
    key_matches = []
    for field in key_fields:
        aliases = _keyword_aliases(field)
        key_matches.append(any(_contains(answer, alias) for alias in aliases))
    key_field_match = bool(key_matches and all(key_matches))

    available_scores = []
    if expected_docs:
        available_scores.append(1.0 if doc_match else 0.0)
    if key_fields:
        available_scores.append(1.0 if key_field_match else 0.0)
    score = sum(available_scores) / len(available_scores) if available_scores else math.nan

    warning_parts: list[str] = []
    if not robust_gold.get("related_original_id") and not robust_gold.get("canonical_question_id"):
        warning_parts.append("no_related_original_id")
    if not expected_docs:
        warning_parts.append("no_expected_same_source_docs")
    if not key_fields:
        warning_parts.append("no_expected_same_key_fields")

    return {
        "robust_query_consistency_score": score,
        "robust_source_doc_match": doc_match,
        "robust_key_field_match": key_field_match,
        "related_original_id": robust_gold.get("related_original_id") or robust_gold.get("canonical_question_id"),
        "robust_warning": "; ".join(warning_parts),
    }

