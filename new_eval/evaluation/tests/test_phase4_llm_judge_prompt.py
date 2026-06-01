"""Phase 4 LLM Judge prompt 생성 테스트."""

from __future__ import annotations

import json

from rag_eval.llm_judge_prompt import (
    build_judge_case_payload,
    build_system_prompt,
    build_user_payload,
    truncate_evidence_summaries,
)
from rag_eval.llm_judge_schema import EvidenceSummary, JudgeInput


def test_system_prompt_contains_required_policy_and_no_zero_placeholder():
    prompt = build_system_prompt()

    assert "RFP" in prompt
    assert "외부 검색" in prompt
    assert "정답지 기반 채점" in prompt
    assert "Phase 1/2/3" in prompt
    assert "instruction-like" in prompt
    assert "JSON" in prompt
    assert "0점" in prompt
    assert '"score": 0' not in prompt
    assert "judge_comment는 한국어" in prompt
    assert "rationale은 한국어" in prompt
    assert "main_strengths" in prompt
    assert "unsupported_or_risky_claims" in prompt
    assert "case_evaluation_ko" in prompt
    assert "strengths_ko" in prompt
    assert "weaknesses_ko" in prompt
    assert "score_rationale_ko" in prompt
    assert "improvement_hint_ko" in prompt
    assert "risk_comment_ko" in prompt


def test_evidence_only_payload_has_no_gold_warning_or_phase_scores():
    judge_input = JudgeInput(
        id="Q001",
        question="예산은?",
        rag_answer="예산은 1억원입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[
            EvidenceSummary(source_file="A.hwp", chunk_id="c1", evidence_summary="예산 근거")
        ],
        domain_gold_summary="gold 요약",
        ground_truth_answer_summary="정답 요약",
        warning_resolution_status="accepted_warning",
        phase1_metrics={"hit_at_5": 1},
    )

    payload = build_judge_case_payload(judge_input, reference_mode="evidence_only")

    assert payload["question"] == "예산은?"
    assert "domain_gold_summary" not in payload
    assert "ground_truth_answer_summary" not in payload
    assert "warning_resolution_status" not in payload
    assert "phase1_metrics" not in payload
    assert payload["rag_answer_truncated"] is False


def test_gold_guided_payload_can_include_gold_summaries():
    judge_input = JudgeInput(
        id="Q001",
        question="예산은?",
        rag_answer="예산은 1억원입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[],
        domain_gold_summary="gold 요약",
        ground_truth_answer_summary="정답 요약",
    )

    payload = build_judge_case_payload(judge_input, reference_mode="gold_guided")

    assert payload["domain_gold_summary"] == "gold 요약"
    assert payload["ground_truth_answer_summary"] == "정답 요약"


def test_user_payload_is_json_data_not_instruction_template():
    judge_input = JudgeInput(
        id="Q001",
        question="마감일은?",
        rag_answer="마감일은 2025-01-01입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[],
    )

    payload_text = build_user_payload(judge_input, reference_mode="evidence_only")
    payload = json.loads(payload_text)

    assert payload["id"] == "Q001"
    assert "평가 기준" not in payload_text
    assert "무조건 높은 점수" not in payload_text


def test_evidence_summaries_are_limited_and_truncation_flagged():
    evidence = [
        EvidenceSummary(source_file=f"A{i}.hwp", chunk_id=f"c{i}", evidence_summary="가" * 500)
        for i in range(7)
    ]

    limited, was_truncated = truncate_evidence_summaries(evidence, max_items=5, max_chars_each=300)

    assert len(limited) == 5
    assert was_truncated is True
    assert all(len(item["evidence_summary"]) <= 300 for item in limited)


def test_completeness_definition_is_limited_to_question_and_evidence():
    prompt = build_system_prompt()

    assert "question과 retrieved_evidence_summaries 기준" in prompt
    assert "전체 RFP 원문 기준" in prompt
