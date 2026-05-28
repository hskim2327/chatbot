"""Phase 4 LLM Judge 결과 파일 저장."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .config import PHASE4_EXPERIMENT_LOG
from .experiment_logger import append_experiment_log
from .llm_judge_schema import SUBSCORE_NAMES
from .path_utils import ensure_dir, ensure_parent, safe_json_value
from .reports import write_dataframe, write_json


RESULT_COLUMNS = [
    "id",
    "question",
    "judge_overall_score",
    "calculated_overall_score",
    "overall_label",
    "business_usefulness_score",
    "business_usefulness_rationale",
    "completeness_score",
    "completeness_rationale",
    "groundedness_score",
    "groundedness_rationale",
    "numeric_factuality_score",
    "numeric_factuality_rationale",
    "structure_clarity_score",
    "structure_clarity_rationale",
    "risk_control_score",
    "risk_control_rationale",
    "risk_level",
    "hallucination_risk",
    "main_strengths",
    "main_weaknesses",
    "unsupported_or_risky_claims",
    "needs_human_review",
    "judge_comment",
    "score_cap_applied",
    "score_cap_reason",
    "score_disagreement_warning",
    "parse_error",
    "validation_error",
    "timeout_error",
    "structured_output_used",
    "fallback_json_mode_used",
    "retry_count",
    "error",
]


def write_jsonl(rows: list[dict[str, Any]], path) -> None:
    """dict row 목록을 JSONL로 저장한다."""

    ensure_parent(path)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(safe_json_value(row), ensure_ascii=False) + "\n")


def flatten_judge_result(row: dict[str, Any]) -> dict[str, Any]:
    """nested JudgeOutput을 CSV 저장용 flat row로 변환한다."""

    flat = {key: row.get(key, "") for key in RESULT_COLUMNS}
    subscores = row.get("subscores") if isinstance(row.get("subscores"), dict) else {}
    for name in SUBSCORE_NAMES:
        subscore = subscores.get(name, {}) if isinstance(subscores.get(name), dict) else {}
        flat[f"{name}_score"] = subscore.get("score", flat.get(f"{name}_score", ""))
        flat[f"{name}_rationale"] = subscore.get("rationale", flat.get(f"{name}_rationale", ""))
    for key in ("main_strengths", "main_weaknesses", "unsupported_or_risky_claims"):
        if isinstance(flat.get(key), (list, dict)):
            flat[key] = json.dumps(flat[key], ensure_ascii=False)
    return flat


def results_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Judge result row 목록을 표준 컬럼 DataFrame으로 만든다."""

    if not rows:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    return pd.DataFrame([flatten_judge_result(row) for row in rows]).reindex(columns=RESULT_COLUMNS)


def _distribution(series: pd.Series) -> dict[str, int]:
    """값 분포를 dict로 반환한다."""

    if series.empty:
        return {}
    return {str(key): int(value) for key, value in series.value_counts(dropna=False).to_dict().items()}


def summarize_results(
    mode: str,
    reference_mode: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    total_inputs: int,
    results_df: pd.DataFrame,
    api_key_present: bool,
) -> dict[str, Any]:
    """Phase 4 결과 요약 dict를 만든다."""

    failed_count = int(results_df.get("error", pd.Series(dtype=str)).astype(str).ne("").sum()) if not results_df.empty else 0
    judged_count = int(len(results_df) - failed_count)
    summary: dict[str, Any] = {
        "mode": mode,
        "reference_mode": reference_mode,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "total_inputs": int(total_inputs),
        "judged_count": judged_count,
        "failed_count": failed_count,
        "parse_error_count": int(results_df.get("parse_error", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0,
        "validation_error_count": int(results_df.get("validation_error", pd.Series(dtype=bool)).eq(True).sum())
        if not results_df.empty
        else 0,
        "timeout_count": 0,
        "api_key_present": bool(api_key_present),
        "mock_or_dry_run": mode in {"mock", "dry_run"},
    }
    if not results_df.empty:
        summary["timeout_count"] = int(results_df.get("timeout_error", pd.Series(dtype=bool)).eq(True).sum())
    summary["retry_count"] = (
        int(pd.to_numeric(results_df.get("retry_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
        if not results_df.empty
        else 0
    )
    summary["structured_output_used"] = (
        bool(results_df.get("structured_output_used", pd.Series(dtype=bool)).eq(True).any()) if not results_df.empty else False
    )
    summary["fallback_json_mode_used"] = (
        bool(results_df.get("fallback_json_mode_used", pd.Series(dtype=bool)).eq(True).any()) if not results_df.empty else False
    )
    score_columns = {
        "average_judge_overall_score": "judge_overall_score",
        "average_calculated_overall_score": "calculated_overall_score",
        "average_business_usefulness_score": "business_usefulness_score",
        "average_completeness_score": "completeness_score",
        "average_groundedness_score": "groundedness_score",
        "average_numeric_factuality_score": "numeric_factuality_score",
        "average_structure_clarity_score": "structure_clarity_score",
        "average_risk_control_score": "risk_control_score",
    }
    for output_key, column in score_columns.items():
        summary[output_key] = (
            float(pd.to_numeric(results_df[column], errors="coerce").mean())
            if column in results_df and not results_df.empty
            else float("nan")
        )
    summary["risk_level_distribution"] = _distribution(results_df["risk_level"]) if "risk_level" in results_df else {}
    summary["hallucination_risk_distribution"] = (
        _distribution(results_df["hallucination_risk"]) if "hallucination_risk" in results_df else {}
    )
    summary["needs_human_review_count"] = (
        int(results_df.get("needs_human_review", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0
    )
    summary["score_cap_applied_count"] = (
        int(results_df.get("score_cap_applied", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0
    )
    summary["score_disagreement_warning_count"] = (
        int(results_df.get("score_disagreement_warning", pd.Series(dtype=bool)).eq(True).sum())
        if not results_df.empty
        else 0
    )
    return summary


def write_llm_judge_summary(path, summary: dict[str, Any]) -> None:
    """Phase 4 LLM Judge 요약 Markdown을 저장한다."""

    ensure_parent(path)
    lines = [
        "# Phase 4 LLM Judge 평가 요약",
        "",
        "이 결과는 Phase 1/2/3 공식 점수를 대체하지 않는 보조 종합 평가입니다.",
    ]
    if summary.get("mock_or_dry_run"):
        lines.append("mock 또는 dry_run 결과는 실제 품질 점수로 해석하지 마십시오.")
    lines.extend(
        [
            "API key 값은 저장하지 않았고, 존재 여부만 boolean으로 기록했습니다.",
            "",
            f"- mode: {summary.get('mode', '')}",
            f"- reference_mode: {summary.get('reference_mode', '')}",
            f"- model: {summary.get('model', '')}",
            f"- prompt_version: {summary.get('prompt_version', '')}",
            f"- schema_version: {summary.get('schema_version', '')}",
            f"- structured_output_used: {summary.get('structured_output_used', False)}",
            f"- fallback_json_mode_used: {summary.get('fallback_json_mode_used', False)}",
            f"- api_key_present: {summary.get('api_key_present', False)}",
            f"- total input count: {summary.get('total_inputs', 0)}",
            f"- judged count: {summary.get('judged_count', 0)}",
            f"- failed count: {summary.get('failed_count', 0)}",
            f"- retry_count: {summary.get('retry_count', 0)}",
            f"- parse_error_count: {summary.get('parse_error_count', 0)}",
            f"- validation_error_count: {summary.get('validation_error_count', 0)}",
            f"- timeout_count: {summary.get('timeout_count', 0)}",
            f"- average judge_overall_score: {summary.get('average_judge_overall_score', '')}",
            f"- average calculated_overall_score: {summary.get('average_calculated_overall_score', '')}",
            f"- average business_usefulness_score: {summary.get('average_business_usefulness_score', '')}",
            f"- average completeness_score: {summary.get('average_completeness_score', '')}",
            f"- average groundedness_score: {summary.get('average_groundedness_score', '')}",
            f"- average numeric_factuality_score: {summary.get('average_numeric_factuality_score', '')}",
            f"- average structure_clarity_score: {summary.get('average_structure_clarity_score', '')}",
            f"- average risk_control_score: {summary.get('average_risk_control_score', '')}",
            f"- risk_level distribution: {summary.get('risk_level_distribution', {})}",
            f"- hallucination_risk distribution: {summary.get('hallucination_risk_distribution', {})}",
            f"- needs_human_review count: {summary.get('needs_human_review_count', 0)}",
            f"- score cap applied count: {summary.get('score_cap_applied_count', 0)}",
            f"- score disagreement warning count: {summary.get('score_disagreement_warning_count', 0)}",
            "",
            "## 주요 감점 원인",
            "",
            "- mock mode에서는 실제 감점 원인을 해석하지 않습니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_llm_judge_reports(
    output_dir,
    judge_inputs: list[dict[str, Any]],
    results_df: pd.DataFrame,
    summary: dict[str, Any],
    failure_df: pd.DataFrame,
    raw_results: list[dict[str, Any]] | None = None,
) -> None:
    """Phase 4 산출물을 저장한다."""

    ensure_dir(output_dir)
    write_jsonl(judge_inputs, output_dir / "phase4_llm_judge_inputs.jsonl")
    write_dataframe(results_df.reindex(columns=RESULT_COLUMNS), output_dir / "phase4_llm_judge_results.csv")
    write_json(raw_results if raw_results is not None else results_df.to_dict(orient="records"), output_dir / "phase4_llm_judge_results.json")
    write_dataframe(failure_df.reindex(columns=RESULT_COLUMNS), output_dir / "phase4_llm_judge_failure_cases.csv")
    write_llm_judge_summary(output_dir / "phase4_llm_judge_summary.md", summary)


def append_llm_judge_experiment_log(output_dir, experiment_meta: dict[str, Any], summary: dict[str, Any]) -> None:
    """Phase 4 experiment log를 append-only CSV로 기록한다."""

    log_dir = output_dir / "experiment_logs"
    append_experiment_log(
        log_dir / PHASE4_EXPERIMENT_LOG,
        {
            "experiment_id": experiment_meta["experiment_id"],
            "experiment_name": experiment_meta.get("experiment_name", ""),
            "run_datetime": experiment_meta["run_datetime"],
            "notes": experiment_meta.get("notes", ""),
            "mode": summary.get("mode", ""),
            "reference_mode": summary.get("reference_mode", ""),
            "provider": summary.get("provider", ""),
            "model": summary.get("model", ""),
            "prompt_version": summary.get("prompt_version", ""),
            "schema_version": summary.get("schema_version", ""),
            "judged_count": summary.get("judged_count", 0),
            "failed_count": summary.get("failed_count", 0),
            "parse_error_count": summary.get("parse_error_count", 0),
            "validation_error_count": summary.get("validation_error_count", 0),
            "timeout_count": summary.get("timeout_count", 0),
            "retry_count": summary.get("retry_count", 0),
            "api_key_present": summary.get("api_key_present", False),
            "structured_output_used": summary.get("structured_output_used", False),
            "fallback_json_mode_used": summary.get("fallback_json_mode_used", False),
            "average_judge_overall_score": summary.get("average_judge_overall_score", ""),
            "average_calculated_overall_score": summary.get("average_calculated_overall_score", ""),
            "average_business_usefulness_score": summary.get("average_business_usefulness_score", ""),
            "average_completeness_score": summary.get("average_completeness_score", ""),
            "average_groundedness_score": summary.get("average_groundedness_score", ""),
            "average_numeric_factuality_score": summary.get("average_numeric_factuality_score", ""),
            "average_structure_clarity_score": summary.get("average_structure_clarity_score", ""),
            "average_risk_control_score": summary.get("average_risk_control_score", ""),
            "risk_level_distribution": summary.get("risk_level_distribution", {}),
            "hallucination_risk_distribution": summary.get("hallucination_risk_distribution", {}),
            "needs_human_review_count": summary.get("needs_human_review_count", 0),
        },
    )
