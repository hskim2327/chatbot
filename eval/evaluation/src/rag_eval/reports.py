"""run별 평가 리포트 파일 저장을 담당한다."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .path_utils import ensure_dir, ensure_parent, safe_json_value


def write_dataframe(df: pd.DataFrame, path) -> None:
    """DataFrame을 UTF-8-SIG CSV로 저장한다."""

    ensure_parent(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(data: Any, path) -> None:
    """JSON 파일을 UTF-8로 저장한다."""

    import json

    ensure_parent(path)
    with path.open("w", encoding="utf-8") as file:
        json.dump(safe_json_value(data), file, ensure_ascii=False, indent=2)


def write_markdown_summary(path, phase1_summary: dict[str, Any], ragas_summary: dict[str, Any] | None = None) -> None:
    """평가 요약 Markdown을 저장한다."""

    ensure_parent(path)
    lines = [
        "# RAG 평가 요약",
        "",
        "## Phase 1 검색 성능",
        "",
        f"- num_eval_questions: {phase1_summary.get('num_eval_questions')}",
        f"- num_scored_questions: {phase1_summary.get('num_scored_questions')}",
        f"- overall_hit_at_5: {phase1_summary.get('overall_hit_at_5')}",
        f"- overall_mrr_at_5: {phase1_summary.get('overall_mrr_at_5')}",
        f"- overall_ndcg_at_5: {phase1_summary.get('overall_ndcg_at_5')}",
    ]
    if "overall_doc_recall_at_5" in phase1_summary:
        lines.extend(
            [
                "",
                "## Phase 1 분석 지표",
                "",
                f"- overall_doc_recall_at_5: {phase1_summary.get('overall_doc_recall_at_5')}",
                f"- overall_multi_doc_recall_at_5: {phase1_summary.get('overall_multi_doc_recall_at_5')}",
            ]
        )
    if ragas_summary is not None:
        lines.extend(["", "## Phase 2 RAGAS", ""])
        for key, value in ragas_summary.items():
            lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(
    output_dir,
    phase1_df: pd.DataFrame,
    phase1_summary: dict[str, Any],
    by_type: pd.DataFrame,
    by_difficulty: pd.DataFrame,
    failure_df: pd.DataFrame,
    ragas_df: pd.DataFrame | None,
    ragas_summary: dict[str, Any] | None,
) -> None:
    """평가 결과 파일을 가능한 범위까지 모두 저장한다."""

    ensure_dir(output_dir)
    write_dataframe(phase1_df, output_dir / "eval_results.csv")
    write_json(phase1_df.to_dict(orient="records"), output_dir / "eval_results.json")
    write_dataframe(by_type, output_dir / "eval_by_type.csv")
    write_dataframe(by_difficulty, output_dir / "eval_by_difficulty.csv")
    write_dataframe(failure_df, output_dir / "failure_cases.csv")
    write_markdown_summary(output_dir / "eval_summary.md", phase1_summary, ragas_summary)
    if ragas_df is not None:
        write_dataframe(ragas_df, output_dir / "ragas_results.csv")
        write_markdown_summary(output_dir / "ragas_summary.md", phase1_summary, ragas_summary or {})

