"""Phase 4 LLM Judge schema 검증 테스트."""

from __future__ import annotations

import pytest

from rag_eval.llm_judge_schema import (
    EvidenceSummary,
    JudgeInput,
    compute_overall_score,
    validate_judge_output,
)


def valid_output() -> dict:
    return {
        "id": "Q001",
        "judge_overall_score": 4,
        "subscores": {
            "business_usefulness": {
                "score": 4,
                "label": "useful",
                "rationale": "근거 범위 안에서 실무적으로 쓸 수 있다.",
                "evidence_refs": [0],
            },
            "completeness": {
                "score": 4,
                "label": "mostly complete",
                "rationale": "질문과 근거 요약 기준으로 주요 항목을 다뤘다.",
                "evidence_refs": [0],
            },
            "groundedness": {
                "score": 5,
                "label": "grounded",
                "rationale": "주요 주장이 근거에 연결된다.",
                "evidence_refs": [0],
            },
            "numeric_factuality": {
                "score": 4,
                "label": "mostly accurate",
                "rationale": "숫자 정보가 크게 어긋나지 않는다.",
                "evidence_refs": [],
            },
            "structure_clarity": {
                "score": 4,
                "label": "clear",
                "rationale": "항목 구분이 명확하다.",
                "evidence_refs": [],
            },
            "risk_control": {
                "score": 5,
                "label": "safe",
                "rationale": "문서 밖 단정을 피했다.",
                "evidence_refs": [],
            },
        },
        "risk_level": "low",
        "hallucination_risk": "low",
        "main_strengths": ["근거 기반"],
        "main_weaknesses": [],
        "unsupported_or_risky_claims": [],
        "needs_human_review": False,
        "judge_comment": "짧은 평가",
        "case_evaluation_ko": "근거 기준으로 대체로 적절하지만 세부 값 확인은 필요합니다.",
        "strengths_ko": ["근거 기반 답변"],
        "weaknesses_ko": [],
        "score_rationale_ko": "근거성과 완전성이 양호해 높은 점수를 받았습니다.",
        "improvement_hint_ko": "핵심 수치와 날짜를 한 번 더 대조하면 좋습니다.",
        "risk_comment_ko": "현재 큰 실무 위험은 낮습니다.",
    }


def test_evidence_only_payload_excludes_gold_warning_and_phase_metrics():
    judge_input = JudgeInput(
        id="Q001",
        question="예산은 얼마인가?",
        rag_answer="예산은 1억원입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[
            EvidenceSummary(source_file="A.hwp", chunk_id="c1", evidence_summary="예산 근거")
        ],
        ground_truth_answer_summary="정답 요약",
        domain_gold_summary="gold 요약",
        task_family="budget",
        source_set="canonical_selected_50",
        warning_resolution_status="resolved",
        phase1_metrics={"hit_at_5": 1},
        phase2_ragas_metrics={"faithfulness": 1.0},
        phase3_domain_metrics={"budget_numeric_accuracy": 1.0},
    )

    payload = judge_input.to_prompt_dict(reference_mode="evidence_only")

    assert set(payload) >= {"id", "question", "rag_answer", "source_docs", "retrieved_evidence_summaries"}
    assert "domain_gold_summary" not in payload
    assert "ground_truth_answer_summary" not in payload
    assert "warning_resolution_status" not in payload
    assert "phase1_metrics" not in payload
    assert "phase2_ragas_metrics" not in payload
    assert "phase3_domain_metrics" not in payload


def test_gold_guided_payload_includes_gold_summaries_only_in_that_mode():
    judge_input = JudgeInput(
        id="Q001",
        question="예산은 얼마인가?",
        rag_answer="예산은 1억원입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[],
        ground_truth_answer_summary="정답 요약",
        domain_gold_summary="gold 요약",
    )

    payload = judge_input.to_prompt_dict(reference_mode="gold_guided")

    assert payload["domain_gold_summary"] == "gold 요약"
    assert payload["ground_truth_answer_summary"] == "정답 요약"
    assert "warning_resolution_status" not in payload


def test_validate_judge_output_accepts_nested_schema_and_postprocesses_score():
    output = validate_judge_output(valid_output(), evidence_count=1)

    assert output["risk_level"] == "low"
    assert output["calculated_overall_score"] >= 4
    assert output["overall_label"] in {"실무 사용 적합", "실무 사용 매우 적합"}
    assert output["parse_error"] is False
    assert output["validation_error"] is False
    assert output["case_evaluation_ko"]
    assert output["strengths_ko"] == ["근거 기반 답변"]


def test_judge_output_schema_requires_korean_explanation_fields():
    from rag_eval.llm_judge_schema import judge_output_json_schema

    schema = judge_output_json_schema()

    for field in (
        "case_evaluation_ko",
        "strengths_ko",
        "weaknesses_ko",
        "score_rationale_ko",
        "improvement_hint_ko",
        "risk_comment_ko",
    ):
        assert field in schema["properties"]
        assert field in schema["required"]


def test_validate_judge_output_rejects_zero_score_placeholder():
    output = valid_output()
    output["judge_overall_score"] = 0

    with pytest.raises(ValueError, match="judge_overall_score"):
        validate_judge_output(output, evidence_count=1)


def test_validate_judge_output_rejects_invalid_risk_level():
    output = valid_output()
    output["risk_level"] = "critical"

    with pytest.raises(ValueError, match="risk_level"):
        validate_judge_output(output, evidence_count=1)


def test_validate_judge_output_rejects_out_of_range_evidence_ref():
    output = valid_output()
    output["subscores"]["business_usefulness"]["evidence_refs"] = [2]

    with pytest.raises(ValueError, match="evidence_refs"):
        validate_judge_output(output, evidence_count=1)


def test_compute_overall_score_applies_cap_rules_and_disagreement_warning():
    output = valid_output()
    output["judge_overall_score"] = 5
    output["risk_level"] = "high"

    result = compute_overall_score(output, question="예산과 마감일은?")

    assert result["calculated_overall_score"] <= 2.5
    assert result["score_cap_applied"] is True
    assert result["score_disagreement_warning"] is True
    assert result["needs_human_review"] is True
