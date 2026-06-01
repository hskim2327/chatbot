"""Phase 3 RFP 도메인 metric 단위 테스트."""

from __future__ import annotations

import pytest

from rag_eval.domain_metrics import (
    compute_budget_numeric_accuracy,
    compute_multi_doc_structure_score,
    compute_required_field_accuracy,
    compute_robust_query_consistency_score,
    compute_unanswerable_refusal_accuracy,
    extract_krw_amounts,
)


def test_extract_krw_amounts_handles_won_and_eok_units():
    amounts = extract_krw_amounts("총 1,000,000원이고 예비 금액은 2.5억원입니다.")

    assert 1_000_000 in amounts
    assert 250_000_000 in amounts


def test_budget_numeric_accuracy_matches_items_and_total():
    gold = {
        "items": [
            {"amount_krw": 100_000_000, "budget_source_type": "project_budget"},
            {"amount_krw": 200_000_000, "budget_source_type": "project_budget"},
        ],
        "total_krw": 300_000_000,
        "tolerance_krw": 0,
        "tolerance_ratio": 0.0,
        "excluded_budget_candidates": [{"amount_krw": 50_000_000}],
    }

    result = compute_budget_numeric_accuracy("두 사업은 1억원과 2억원이며 총 3억원입니다.", gold)

    assert result["budget_numeric_accuracy"] == pytest.approx(1.0)
    assert result["budget_item_match_count"] == 2
    assert result["budget_total_match"] is True


def test_required_field_accuracy_scores_keyword_and_checklist_partial():
    gold = {
        "fields": [
            {
                "field_name": "major_requirements",
                "match_type": "checklist_coverage",
                "expected_keywords": ["인프라 고도화", "운영 안정성"],
                "required": True,
                "weight": 1.0,
            },
            {
                "field_name": "project_duration",
                "match_type": "keyword_coverage",
                "expected_keywords": ["착수일", "완료일"],
                "min_match_count": 2,
                "required": True,
                "weight": 1.0,
            },
        ]
    }

    result = compute_required_field_accuracy("인프라 고도화와 운영 안정성을 목표로 하며 착수일이 제시됩니다.", gold)

    assert result["required_field_accuracy"] == pytest.approx(0.5)
    assert "project_duration" in result["required_field_missing_items"]


def test_unanswerable_refusal_accuracy_penalizes_forbidden_claim():
    gold = {
        "is_unanswerable": True,
        "allowed_refusal_phrases": ["확인할 수 없습니다"],
        "forbidden_claim_types": ["낙찰업체 단정"],
        "forbidden_hallucination_patterns": ["A사가 낙찰"],
    }

    result = compute_unanswerable_refusal_accuracy("제공된 자료에서는 확인할 수 없습니다. 다만 A사가 낙찰된 것으로 보입니다.", gold)

    assert result["refusal_phrase_found"] is True
    assert result["forbidden_claim_found"] is True
    assert result["unanswerable_refusal_accuracy"] == pytest.approx(0.5)


def test_multi_doc_structure_score_checks_docs_axes_and_structure():
    gold = {
        "compared_docs": ["A.hwp", "B.hwp"],
        "required_comparison_axes": ["예산", "사업목표"],
        "required_output_structure": ["공통점", "차이점"],
    }
    contexts = [{"filename": "A.hwp"}, {"filename": "B.hwp"}]

    result = compute_multi_doc_structure_score("공통점은 사업목표이고 차이점은 예산입니다.", gold, contexts)

    assert result["doc_coverage_score"] == pytest.approx(1.0)
    assert result["comparison_axis_score"] == pytest.approx(1.0)
    assert result["output_structure_score"] == pytest.approx(1.0)
    assert result["multi_doc_structure_score"] == pytest.approx(1.0)


def test_robust_query_consistency_allows_missing_related_id_with_warning():
    gold = {
        "canonical_question_id": None,
        "related_original_id": None,
        "expected_same_source_docs": ["doc-a.hwp"],
        "expected_same_key_fields": ["예산"],
    }
    contexts = [{"rank": 1, "filename": "doc-a.hwp"}]

    result = compute_robust_query_consistency_score("예산은 1억원입니다.", gold, contexts)

    assert result["robust_query_consistency_score"] == pytest.approx(1.0)
    assert result["robust_source_doc_match"] is True
    assert result["robust_key_field_match"] is True
