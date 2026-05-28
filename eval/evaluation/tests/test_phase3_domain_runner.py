"""Phase 3 domain runner 통합 동작 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from rag_eval.domain_gold_loader import load_domain_gold
from rag_eval.domain_runner import run_domain_evaluation
from rag_eval.runner import main


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def sample_gold_rows() -> list[dict]:
    return [
        {
            "id": "D001",
            "source_set": "test",
            "question": "예산은?",
            "task_family": "budget",
            "secondary_task_families": [],
            "question_type": "A",
            "difficulty": "하",
            "human_verified": True,
            "review_status": "verified",
            "final_use_decision": "keep",
            "source_docs": ["doc-a.hwp"],
            "gold_generation_status": "complete",
            "gold_generation_warnings": [],
            "warning_resolution_status": "",
            "warning_resolution_notes": "",
            "can_use_for_phase3": True,
            "budget_gold": {
                "items": [{"amount_krw": 100_000_000, "budget_source_type": "project_budget"}],
                "total_krw": 100_000_000,
                "tolerance_krw": 0,
                "tolerance_ratio": 0.0,
                "excluded_budget_candidates": [],
            },
        },
        {
            "id": "D002",
            "source_set": "test",
            "question": "사용 제외",
            "task_family": "unanswerable",
            "secondary_task_families": [],
            "question_type": "D",
            "difficulty": "하",
            "human_verified": True,
            "review_status": "verified",
            "final_use_decision": "keep",
            "source_docs": ["doc-b.hwp"],
            "gold_generation_status": "needs_fix",
            "gold_generation_warnings": [],
            "warning_resolution_status": "",
            "warning_resolution_notes": "",
            "can_use_for_phase3": False,
            "unanswerable_gold": {"is_unanswerable": True},
        },
        {
            "id": "D003",
            "source_set": "test",
            "question": "경고 포함",
            "task_family": "robust_query_type_e",
            "secondary_task_families": [],
            "question_type": "E",
            "difficulty": "중",
            "human_verified": True,
            "review_status": "verified",
            "final_use_decision": "keep",
            "source_docs": ["doc-c.hwp"],
            "gold_generation_status": "complete_with_warnings",
            "gold_generation_warnings": ["accepted"],
            "warning_resolution_status": "accepted_warning",
            "warning_resolution_notes": "평가 가능",
            "can_use_for_phase3": True,
            "robust_query_gold": {
                "related_original_id": None,
                "canonical_question_id": None,
                "expected_same_source_docs": ["doc-c.hwp"],
                "expected_same_key_fields": ["예산"],
            },
        },
    ]


def test_domain_gold_loader_excludes_false_but_keeps_accepted_warning(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())

    records, skipped = load_domain_gold(gold_path)

    assert [record["id"] for record in records] == ["D001", "D003"]
    assert [record["id"] for record in skipped] == ["D002"]


def test_domain_runner_writes_outputs_and_log(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(gold_path, sample_gold_rows())
    predictions = pd.DataFrame(
        [
            {"id": "D001", "question": "예산은?", "answer": "예산은 1억원입니다.", "retrieved_contexts": []},
            {
                "id": "D003",
                "question": "경고 포함",
                "answer": "예산은 1억원입니다.",
                "retrieved_contexts": [{"rank": 1, "filename": "doc-c.hwp"}],
            },
        ]
    )
    output_dir = tmp_path / "out"
    meta = {
        "experiment_id": "exp1",
        "experiment_name": "domain",
        "run_datetime": "2026-05-27T00:00:00",
        "notes": "test",
    }

    result = run_domain_evaluation(gold_path, predictions, output_dir, meta)

    assert result.summary["evaluated_count"] == 2
    assert result.summary["skipped_count"] == 1
    assert result.summary["accepted_warning_count"] == 1
    assert (output_dir / "phase3_domain_results.csv").exists()
    assert (output_dir / "phase3_domain_summary.md").exists()
    assert (output_dir / "experiment_logs" / "phase3_domain_experiments.csv").exists()


def test_runner_help_contains_domain_flags(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])

    out = capsys.readouterr().out
    assert "--enable-domain" in out
    assert "--domain-gold-path" in out
