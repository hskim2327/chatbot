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
    assert "실제 품질 점수로 해석하지 마십시오" in (output_dir / "phase4_llm_judge_summary.md").read_text(
        encoding="utf-8"
    )

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
