"""평가 결과 집계와 실패 사례 분류를 담당한다."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import PHASE1_ANALYSIS_COLUMNS, PHASE1_METRIC_COLUMNS


def aggregate_phase1(phase1_df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """overall/type/difficulty 단위로 Phase 1 평균을 계산한다."""

    overall = {
        "overall_hit_at_5": float(phase1_df["hit_at_5"].mean(skipna=True)),
        "overall_mrr_at_5": float(phase1_df["mrr_at_5"].mean(skipna=True)),
        "overall_ndcg_at_5": float(phase1_df["ndcg_at_5"].mean(skipna=True)),
        "num_eval_questions": int(len(phase1_df)),
        "num_scored_questions": int(phase1_df["hit_at_5"].notna().sum()),
    }
    for column in PHASE1_ANALYSIS_COLUMNS:
        if column in phase1_df.columns:
            overall[f"overall_{column}"] = float(phase1_df[column].mean(skipna=True))

    metric_columns = [
        column
        for column in (*PHASE1_METRIC_COLUMNS, *PHASE1_ANALYSIS_COLUMNS)
        if column in phase1_df.columns
    ]
    by_type = phase1_df.groupby("type", dropna=False)[metric_columns].mean().reset_index()
    by_difficulty = phase1_df.groupby("difficulty", dropna=False)[metric_columns].mean().reset_index()
    return overall, by_type, by_difficulty


def summarize_ragas(ragas_df: pd.DataFrame) -> dict[str, Any]:
    """RAGAS 결과의 평균과 오류 개수를 요약한다."""

    errors = ragas_df.get("ragas_error", pd.Series(dtype=str)).astype(str).ne("")
    summary: dict[str, Any] = {"ragas_error_count": int(errors.sum())}
    for column in ("faithfulness", "answer_relevancy", "response_relevancy", "context_precision", "context_recall"):
        if column in ragas_df.columns:
            summary[f"mean_{column}"] = float(pd.to_numeric(ragas_df[column], errors="coerce").mean(skipna=True))
    return summary


def build_failure_cases(phase1_df: pd.DataFrame, ragas_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Phase 1과 RAGAS 결과를 바탕으로 실패 사례를 모은다."""

    failure_df = phase1_df[
        phase1_df["hit_at_5"].fillna(0).lt(1)
        | phase1_df["mrr_at_5"].fillna(0).eq(0)
        | phase1_df["ndcg_at_5"].fillna(0).lt(1)
    ].copy()
    failure_df["failure_reason"] = "retrieval_failure"

    if ragas_df is not None and not ragas_df.empty:
        ragas_errors = ragas_df[ragas_df.get("ragas_error", "").astype(str).ne("")]
        if not ragas_errors.empty:
            error_cases = ragas_errors[["id", "ragas_error"]].copy()
            error_cases["failure_reason"] = "ragas_error"
            failure_df = pd.concat([failure_df, error_cases], ignore_index=True, sort=False)
    return failure_df
