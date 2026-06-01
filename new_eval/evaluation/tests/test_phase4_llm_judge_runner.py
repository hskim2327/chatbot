"""Phase 4 LLM Judge runner 테스트."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from rag_eval.llm_judge_config import load_llm_judge_settings
from rag_eval.llm_judge_runner import run_llm_judge_evaluation
from rag_eval.runner import build_arg_parser


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_gold_rows():
    return [
        {
            "id": "Q001",
            "source_set": "canonical_selected_50",
            "question": "예산은 얼마인가?",
            "task_family": "budget",
            "question_type": "A",
            "difficulty": "하",
            "source_docs": ["A.hwp"],
            "warning_resolution_status": "resolved",
            "can_use_for_phase3": True,
            "budget_gold": {
                "items": [{"label": "A", "amount_krw": 100000000, "budget_source_type": "project_budget"}],
                "total_krw": 100000000,
            },
        },
        {
            "id": "Q002",
            "source_set": "canonical_selected_50",
            "question": "최종 낙찰업체는?",
            "task_family": "unanswerable",
            "question_type": "D",
            "difficulty": "중",
            "source_docs": ["B.hwp"],
            "warning_resolution_status": "accepted_warning",
            "can_use_for_phase3": True,
            "unanswerable_gold": {
                "is_unanswerable": True,
                "allowed_refusal_phrases": ["확인할 수 없습니다"],
                "forbidden_claim_types": ["낙찰업체 단정"],
            },
        },
    ]


def sample_predictions():
    return pd.DataFrame(
        [
            {
                "id": "Q001",
                "question": "예산은 얼마인가?",
                "answer": "예산은 1억원입니다.",
                "latency_ms": 2500,
                "retrieved_contexts": [
                    {"rank": 1, "filename": "A.hwp", "chunk_id": "c1", "text": "예산 근거 요약"}
                ],
            },
            {
                "id": "Q002",
                "question": "최종 낙찰업체는?",
                "answer": "제공된 자료에는 최종 낙찰업체가 명시되어 있지 않습니다.",
                "latency_sec": 1.2,
                "retrieved_contexts": [],
            },
        ]
    )


def test_runner_help_contains_reference_mode_flag():
    help_text = build_arg_parser().format_help()

    assert "--enable-llm-judge" in help_text
    assert "--llm-judge-mode" in help_text
    assert "--llm-judge-reference-mode" in help_text


def test_mock_mode_writes_nested_results_and_log(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())

    result = run_llm_judge_evaluation(
        predictions_df=sample_predictions(),
        domain_gold_path=gold_path,
        output_dir=tmp_path / "out",
        experiment_meta={"experiment_id": "exp4", "experiment_name": "mock", "run_datetime": "2026-05-27", "notes": ""},
        mode="mock",
        reference_mode="evidence_only",
    )

    assert result.summary["judged_count"] == 2
    assert result.summary["reference_mode"] == "evidence_only"
    assert "calculated_overall_score" in result.results.columns
    assert "answer_latency_sec" in result.results.columns
    assert "문항별 한글 총평" in result.results.columns
    assert "case_evaluation_ko" in result.results.columns
    assert "strengths_ko" in result.results.columns
    assert "weaknesses_ko" in result.results.columns
    assert "improvement_hint_ko" in result.results.columns
    assert result.results["case_evaluation_ko"].astype(str).str.len().gt(0).all()
    assert result.summary["average_answer_latency_sec"] > 0
    assert (tmp_path / "out" / "phase4_llm_judge_inputs.jsonl").exists()
    assert (tmp_path / "out" / "phase4_llm_judge_results.csv").exists()
    assert (tmp_path / "out" / "experiment_logs" / "phase4_llm_judge_experiments.csv").exists()

    inputs_text = (tmp_path / "out" / "phase4_llm_judge_inputs.jsonl").read_text(encoding="utf-8")
    assert "domain_gold_summary" not in inputs_text
    assert "warning_resolution_status" not in inputs_text


def test_dry_run_writes_inputs_without_judged_results(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())

    result = run_llm_judge_evaluation(
        predictions_df=sample_predictions(),
        domain_gold_path=gold_path,
        output_dir=tmp_path / "out",
        experiment_meta={"experiment_id": "exp4", "experiment_name": "dry", "run_datetime": "2026-05-27", "notes": ""},
        mode="dry_run",
        reference_mode="evidence_only",
    )

    assert result.summary["judged_count"] == 0
    assert result.summary["total_inputs"] == 2
    assert (tmp_path / "out" / "phase4_llm_judge_inputs.jsonl").exists()


def test_gold_guided_mode_writes_gold_summaries_to_inputs(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())

    run_llm_judge_evaluation(
        predictions_df=sample_predictions(),
        domain_gold_path=gold_path,
        output_dir=tmp_path / "out",
        experiment_meta={"experiment_id": "exp4", "experiment_name": "gold", "run_datetime": "2026-05-27", "notes": ""},
        mode="dry_run",
        reference_mode="gold_guided",
    )

    inputs_text = (tmp_path / "out" / "phase4_llm_judge_inputs.jsonl").read_text(encoding="utf-8")
    assert "domain_gold_summary" in inputs_text
    assert "ground_truth_answer_summary" in inputs_text


def test_api_mode_without_key_fails_safely(tmp_path, monkeypatch):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API key"):
        run_llm_judge_evaluation(
            predictions_df=sample_predictions(),
            domain_gold_path=gold_path,
            output_dir=tmp_path / "out",
            experiment_meta={"experiment_id": "exp4", "experiment_name": "api", "run_datetime": "2026-05-27", "notes": ""},
            mode="api",
            settings=load_llm_judge_settings(evaluation_root=tmp_path),
        )


def test_api_mode_with_key_but_without_model_fails_before_api_call(tmp_path, monkeypatch):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")

    with pytest.raises(RuntimeError, match="model"):
        run_llm_judge_evaluation(
            predictions_df=sample_predictions(),
            domain_gold_path=gold_path,
            output_dir=tmp_path / "out",
            experiment_meta={"experiment_id": "exp4", "experiment_name": "api", "run_datetime": "2026-05-27", "notes": ""},
            mode="api",
            settings=load_llm_judge_settings(evaluation_root=tmp_path),
        )
