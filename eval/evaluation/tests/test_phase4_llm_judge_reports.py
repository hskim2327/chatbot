"""Phase 4 LLM Judge report 저장 테스트."""

from __future__ import annotations

import pandas as pd

from rag_eval.llm_judge_reports import append_llm_judge_experiment_log, write_llm_judge_reports


def test_reports_write_expected_files_and_do_not_expose_api_key(tmp_path):
    output_dir = tmp_path / "out"
    inputs = [{"id": "Q001", "question": "질문", "rag_answer": "답변"}]
    results_df = pd.DataFrame(
        [
            {
                "id": "Q001",
                "question": "질문",
                "judge_overall_score": 4,
                "calculated_overall_score": 4.1,
                "overall_label": "실무 사용 적합",
                "business_usefulness_score": 4,
                "business_usefulness_rationale": "쓸 수 있음",
                "completeness_score": 4,
                "completeness_rationale": "충분함",
                "groundedness_score": 4,
                "groundedness_rationale": "근거 있음",
                "numeric_factuality_score": 4,
                "numeric_factuality_rationale": "정확함",
                "structure_clarity_score": 4,
                "structure_clarity_rationale": "명확함",
                "risk_control_score": 4,
                "risk_control_rationale": "위험 낮음",
                "risk_level": "low",
                "hallucination_risk": "low",
                "main_strengths": ["강점"],
                "main_weaknesses": [],
                "unsupported_or_risky_claims": [],
                "needs_human_review": False,
                "judge_comment": "요약",
                "answer_latency_sec": 2.5,
                "latency_note": "predictions latency_ms 기준",
                "case_evaluation_ko": "근거가 충분하고 위험한 단정이 적습니다.",
                "strengths_ko": ["근거 기반 답변"],
                "weaknesses_ko": [],
                "score_rationale_ko": "근거성과 완전성이 양호합니다.",
                "improvement_hint_ko": "핵심 수치를 한 번 더 확인하면 좋습니다.",
                "risk_comment_ko": "큰 실무 위험은 낮습니다.",
                "문항별 한글 총평": "근거가 충분하고 위험한 단정이 적습니다.",
                "종합 점수": 4.1,
                "종합 판정": "실무 사용 적합",
                "답변 생성 시간초": 2.5,
                "실패 사유 한글 요약": "",
                "점수 근거 한글 요약": "근거성과 완전성이 양호합니다.",
                "score_cap_applied": False,
                "score_cap_reason": "",
                "score_disagreement_warning": False,
                "parse_error": False,
                "validation_error": False,
                "error": "",
            }
        ]
    )
    summary = {
        "mode": "mock",
        "reference_mode": "evidence_only",
        "model": "",
        "prompt_version": "phase4_judge_v1",
        "schema_version": "phase4_judge_schema_v1",
        "total_inputs": 1,
        "judged_count": 1,
        "failed_count": 0,
        "api_key_present": True,
        "average_judge_overall_score": 4.0,
        "average_calculated_overall_score": 4.1,
        "average_answer_latency_sec": 2.5,
        "median_answer_latency_sec": 2.5,
        "max_answer_latency_sec": 2.5,
        "risk_level_distribution": {"low": 1},
        "hallucination_risk_distribution": {"low": 1},
        "needs_human_review_count": 0,
        "score_cap_applied_count": 0,
        "score_disagreement_warning_count": 0,
        "mock_or_dry_run": True,
    }

    write_llm_judge_reports(output_dir, inputs, results_df, summary, pd.DataFrame())

    assert (output_dir / "phase4_llm_judge_inputs.jsonl").exists()
    assert (output_dir / "phase4_llm_judge_results.csv").exists()
    assert (output_dir / "phase4_llm_judge_results.json").exists()
    assert (output_dir / "phase4_llm_judge_summary.md").exists()
    assert (output_dir / "phase4_llm_judge_failure_cases.csv").exists()
    summary_text = (output_dir / "phase4_llm_judge_summary.md").read_text(encoding="utf-8")
    results_csv = pd.read_csv(output_dir / "phase4_llm_judge_results.csv")

    assert "Phase 4 LLM Judge 평가 요약" in summary_text
    assert "종합 점수" in summary_text
    assert "전체 판정" in summary_text
    assert "레이턴시 참고 지표" in summary_text
    assert "전체 평가 총평" in summary_text
    assert "주요 강점" in summary_text
    assert "개선 우선순위" in summary_text
    assert "answer_latency_sec" in results_csv.columns
    assert "답변 생성 시간초" in results_csv.columns
    assert "문항별 한글 총평" in results_csv.columns
    assert "case_evaluation_ko" in results_csv.columns
    assert "strengths_ko" in results_csv.columns
    assert "weaknesses_ko" in results_csv.columns
    assert "score_rationale_ko" in results_csv.columns
    assert "improvement_hint_ko" in results_csv.columns
    assert "risk_comment_ko" in results_csv.columns
    assert "calculated_overall_score" in results_csv.columns
    assert "실제 품질 점수로 해석하지 마십시오" in summary_text

    combined = "\n".join(path.read_text(encoding="utf-8-sig", errors="ignore") for path in output_dir.glob("phase4_*"))
    assert "test-secret-value" not in combined


def test_experiment_log_is_append_only_and_has_reference_mode(tmp_path):
    output_dir = tmp_path / "out"
    meta = {"experiment_id": "exp", "experiment_name": "name", "run_datetime": "2026-05-27", "notes": "note"}
    summary = {
        "mode": "mock",
        "reference_mode": "evidence_only",
        "provider": "openai",
        "model": "mock-model",
        "prompt_version": "phase4_judge_v1",
        "schema_version": "phase4_judge_schema_v1",
        "judged_count": 1,
        "failed_count": 0,
        "parse_error_count": 0,
        "validation_error_count": 0,
        "timeout_count": 0,
        "api_key_present": False,
        "average_judge_overall_score": 3.0,
        "average_calculated_overall_score": 3.0,
        "average_business_usefulness_score": 3.0,
        "average_completeness_score": 3.0,
        "average_groundedness_score": 3.0,
        "average_numeric_factuality_score": 3.0,
        "average_structure_clarity_score": 3.0,
        "average_risk_control_score": 3.0,
        "risk_level_distribution": {"low": 1},
        "hallucination_risk_distribution": {"low": 1},
        "needs_human_review_count": 0,
    }

    append_llm_judge_experiment_log(output_dir, meta, summary)
    append_llm_judge_experiment_log(output_dir, meta, summary)

    log_path = output_dir / "experiment_logs" / "phase4_llm_judge_experiments.csv"
    df = pd.read_csv(log_path)

    assert len(df) == 2
    assert "reference_mode" in df.columns
    assert "api_key_present" in df.columns
