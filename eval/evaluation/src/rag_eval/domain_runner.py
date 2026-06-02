"""Phase 3 RFP 도메인 평가 실행 흐름을 담당한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import PHASE3_EXPERIMENT_LOG
from .domain_gold_loader import load_domain_gold
from .domain_metrics import (
    compute_budget_numeric_accuracy,
    compute_multi_doc_structure_score,
    compute_required_field_accuracy,
    compute_robust_query_consistency_score,
    compute_submission_eligibility_deadline_accuracy,
    compute_unanswerable_refusal_accuracy,
)
from .domain_reports import write_domain_reports
from .experiment_logger import append_experiment_log


PHASE3_METRIC_COLUMNS = (
    "budget_numeric_accuracy",
    "required_field_accuracy",
    "unanswerable_refusal_accuracy",
    "multi_doc_structure_score",
    "robust_query_consistency_score",
)


@dataclass
class DomainEvaluationResult:
    """Phase 3 실행 결과를 테스트와 runner가 함께 쓰기 위한 컨테이너다."""

    results: pd.DataFrame
    summary: dict[str, Any]
    by_task: pd.DataFrame
    warning_summary: dict[str, Any]
    failure_cases: pd.DataFrame


def _nan() -> float:
    """DataFrame에 넣을 NaN 값을 만든다."""

    return float("nan")


def _mean(series: pd.Series) -> float:
    """NaN을 제외한 평균을 계산한다."""

    value = pd.to_numeric(series, errors="coerce").mean()
    return float(value) if not pd.isna(value) else math.nan


def _latency_sec(prediction: dict[str, Any] | None) -> float:
    """prediction의 latency 값을 초 단위 참고값으로 정규화한다."""

    if prediction is None:
        return _nan()
    if prediction.get("latency_sec") not in (None, ""):
        value = pd.to_numeric(pd.Series([prediction.get("latency_sec")]), errors="coerce").iloc[0]
        return float(value) if not pd.isna(value) else _nan()
    if prediction.get("latency_ms") not in (None, ""):
        value = pd.to_numeric(pd.Series([prediction.get("latency_ms")]), errors="coerce").iloc[0]
        return float(value) / 1000.0 if not pd.isna(value) else _nan()
    return _nan()


def _empty_metric_row() -> dict[str, Any]:
    """모든 Phase 3 metric 컬럼의 기본값을 만든다."""

    return {
        "budget_numeric_accuracy": _nan(),
        "budget_item_match_count": _nan(),
        "budget_item_total_count": _nan(),
        "budget_total_match": None,
        "budget_parse_error": "",
        "budget_warning": "",
        "required_field_accuracy": _nan(),
        "required_field_matched_count": _nan(),
        "required_field_total_count": _nan(),
        "required_field_missing_items": [],
        "submission_documents_coverage": _nan(),
        "eligibility_terms_coverage": _nan(),
        "deadline_match": None,
        "required_field_warning": "",
        "unanswerable_refusal_accuracy": _nan(),
        "refusal_phrase_found": None,
        "forbidden_claim_found": None,
        "forbidden_claim_matches": [],
        "unanswerable_warning": "",
        "multi_doc_structure_score": _nan(),
        "doc_coverage_score": _nan(),
        "comparison_axis_score": _nan(),
        "output_structure_score": _nan(),
        "multi_doc_warning": "",
        "robust_query_consistency_score": _nan(),
        "robust_source_doc_match": None,
        "robust_key_field_match": None,
        "related_original_id": "",
        "robust_warning": "",
    }


def _task_score(task_family: str, metrics: dict[str, Any]) -> float:
    """task_family별 대표 Phase 3 점수를 선택한다."""

    mapping = {
        "budget": "budget_numeric_accuracy",
        "required_fields": "required_field_accuracy",
        "submission_eligibility_deadline": "required_field_accuracy",
        "unanswerable": "unanswerable_refusal_accuracy",
        "multi_doc_comparison": "multi_doc_structure_score",
        "robust_query_type_e": "robust_query_consistency_score",
    }
    return metrics.get(mapping.get(task_family, ""), _nan())


def evaluate_domain_record(gold: dict[str, Any], prediction: dict[str, Any] | None) -> dict[str, Any]:
    """gold record와 prediction 한 쌍을 Phase 3 metric으로 평가한다."""

    task_family = str(gold.get("task_family", ""))
    answer = "" if prediction is None else str(prediction.get("answer", "") or "")
    retrieved_contexts = [] if prediction is None else prediction.get("retrieved_contexts", [])
    metrics = _empty_metric_row()
    error = ""
    warning_parts: list[str] = []

    if prediction is None:
        error = "prediction_missing"
    else:
        try:
            if task_family == "budget":
                metrics.update(compute_budget_numeric_accuracy(answer, gold.get("budget_gold") or {}))
            elif task_family == "required_fields":
                metrics.update(compute_required_field_accuracy(answer, gold.get("required_field_gold") or {}))
            elif task_family == "submission_eligibility_deadline":
                metrics.update(
                    compute_submission_eligibility_deadline_accuracy(
                        answer,
                        gold.get("submission_eligibility_deadline_gold") or {},
                    )
                )
            elif task_family == "unanswerable":
                metrics.update(compute_unanswerable_refusal_accuracy(answer, gold.get("unanswerable_gold") or {}))
            elif task_family == "multi_doc_comparison":
                metrics.update(
                    compute_multi_doc_structure_score(
                        answer,
                        gold.get("multi_doc_comparison_gold") or {},
                        retrieved_contexts,
                    )
                )
            elif task_family == "robust_query_type_e":
                metrics.update(
                    compute_robust_query_consistency_score(
                        answer,
                        gold.get("robust_query_gold") or {},
                        retrieved_contexts,
                    )
                )
            else:
                error = f"unsupported_task_family:{task_family}"
        except Exception as exc:  # pragma: no cover - 개별 row 실패 격리용
            error = f"metric_error:{exc}"

    for key in ("budget_warning", "required_field_warning", "unanswerable_warning", "multi_doc_warning", "robust_warning"):
        value = metrics.get(key)
        if value:
            warning_parts.append(str(value))

    if gold.get("warning_resolution_status") == "accepted_warning":
        warning_parts.append("accepted_warning")

    metrics["phase3_task_score"] = _task_score(task_family, metrics)
    metrics["error"] = error
    metrics["warning"] = "; ".join(dict.fromkeys(warning_parts))
    return metrics


def _base_result_row(gold: dict[str, Any], prediction: dict[str, Any] | None) -> dict[str, Any]:
    """Phase 3 결과 row의 공통 컬럼을 만든다."""

    return {
        "id": gold.get("id", ""),
        "question": gold.get("question", ""),
        "task_family": gold.get("task_family", ""),
        "source_set": gold.get("source_set", ""),
        "question_type": gold.get("question_type", ""),
        "difficulty": gold.get("difficulty", ""),
        "answer": "" if prediction is None else prediction.get("answer", ""),
        "can_use_for_phase3": gold.get("can_use_for_phase3", True),
        "gold_generation_status": gold.get("gold_generation_status", ""),
        "warning_resolution_status": gold.get("warning_resolution_status", ""),
        "warning_resolution_notes": gold.get("warning_resolution_notes", ""),
        "phase3_applicable": prediction is not None,
        "answer_latency_sec": _latency_sec(prediction),
    }


def build_domain_results(
    usable_gold: list[dict[str, Any]],
    predictions_df: pd.DataFrame,
    sample_size: int = 0,
) -> pd.DataFrame:
    """gold와 prediction을 id 기준으로 매칭해 Phase 3 row-level 결과를 만든다."""

    records = usable_gold[: sample_size] if sample_size and sample_size > 0 else usable_gold
    prediction_map = {str(row.get("id")): row for row in predictions_df.to_dict(orient="records")}
    rows: list[dict[str, Any]] = []

    for gold in records:
        prediction = prediction_map.get(str(gold.get("id")))
        row = _base_result_row(gold, prediction)
        row.update(evaluate_domain_record(gold, prediction))
        rows.append(row)

    return pd.DataFrame(rows)


def aggregate_domain_results(
    results_df: pd.DataFrame,
    total_gold_count: int,
    skipped_count: int,
    accepted_warning_count: int,
    can_use_false_count: int,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Phase 3 overall/task/warning/failure 요약을 만든다."""

    evaluated_mask = results_df["phase3_applicable"].eq(True) & results_df["error"].astype(str).eq("")
    summary = {
        "total_gold_count": int(total_gold_count),
        "evaluated_count": int(evaluated_mask.sum()),
        "skipped_count": int(skipped_count + (~results_df["phase3_applicable"].eq(True)).sum()),
        "phase3_task_score_mean": _mean(results_df.loc[evaluated_mask, "phase3_task_score"]),
        "accepted_warning_count": int(accepted_warning_count),
        "can_use_for_phase3_false_count": int(can_use_false_count),
    }
    for column in PHASE3_METRIC_COLUMNS:
        summary[f"{column}_mean"] = _mean(results_df.loc[evaluated_mask, column])

    task_rows: list[dict[str, Any]] = []
    for task_family, group in results_df.groupby("task_family", dropna=False):
        group_eval = group["phase3_applicable"].eq(True) & group["error"].astype(str).eq("")
        row = {
            "task_family": task_family,
            "count": int(len(group)),
            "evaluated_count": int(group_eval.sum()),
            "phase3_task_score_mean": _mean(group.loc[group_eval, "phase3_task_score"]),
            "warning_count": int(group["warning"].astype(str).ne("").sum()),
            "failure_count": int((pd.to_numeric(group["phase3_task_score"], errors="coerce") < 1.0).sum()),
        }
        for column in PHASE3_METRIC_COLUMNS:
            row[f"{column}_mean"] = _mean(group.loc[group_eval, column])
        task_rows.append(row)
    by_task = pd.DataFrame(task_rows)

    warning_summary = {
        "warning_resolution_status_counts": results_df["warning_resolution_status"].value_counts(dropna=False).to_dict()
        if "warning_resolution_status" in results_df
        else {},
        "gold_generation_status_counts": results_df["gold_generation_status"].value_counts(dropna=False).to_dict()
        if "gold_generation_status" in results_df
        else {},
        "accepted_warning_ids": results_df.loc[
            results_df["warning_resolution_status"].astype(str).eq("accepted_warning"), "id"
        ].tolist(),
        "metric_warning_ids": results_df.loc[results_df["warning"].astype(str).ne(""), "id"].tolist(),
        "metric_error_ids": results_df.loc[results_df["error"].astype(str).ne(""), "id"].tolist(),
    }

    failure_df = results_df[
        results_df["error"].astype(str).ne("")
        | (pd.to_numeric(results_df["phase3_task_score"], errors="coerce") < 1.0)
    ].copy()
    return summary, by_task, warning_summary, failure_df


def append_domain_experiment_log(
    output_dir,
    experiment_meta: dict[str, Any],
    summary: dict[str, Any],
    domain_gold_path,
) -> None:
    """Phase 3 실험 로그를 append-only CSV에 기록한다."""

    log_dir = output_dir / "experiment_logs"
    append_experiment_log(
        log_dir / PHASE3_EXPERIMENT_LOG,
        {
            "experiment_id": experiment_meta["experiment_id"],
            "experiment_name": experiment_meta.get("experiment_name", ""),
            "run_datetime": experiment_meta["run_datetime"],
            "notes": experiment_meta.get("notes", ""),
            "domain_gold_path": str(domain_gold_path),
            "gold_record_count": summary.get("total_gold_count", 0),
            "evaluated_count": summary.get("evaluated_count", 0),
            "accepted_warning_count": summary.get("accepted_warning_count", 0),
            "can_use_for_phase3_false_count": summary.get("can_use_for_phase3_false_count", 0),
            "phase3_task_score_mean": summary.get("phase3_task_score_mean", math.nan),
            "budget_numeric_accuracy_mean": summary.get("budget_numeric_accuracy_mean", math.nan),
            "required_field_accuracy_mean": summary.get("required_field_accuracy_mean", math.nan),
            "unanswerable_refusal_accuracy_mean": summary.get("unanswerable_refusal_accuracy_mean", math.nan),
            "multi_doc_structure_score_mean": summary.get("multi_doc_structure_score_mean", math.nan),
            "robust_query_consistency_score_mean": summary.get("robust_query_consistency_score_mean", math.nan),
        },
    )


def run_domain_evaluation(
    domain_gold_path,
    predictions_df: pd.DataFrame,
    output_dir,
    experiment_meta: dict[str, Any] | None = None,
    sample_size: int = 0,
) -> DomainEvaluationResult:
    """Phase 3 도메인 평가를 실행하고 결과 파일과 실험 로그를 저장한다."""

    usable_gold, skipped_gold = load_domain_gold(domain_gold_path)
    results_df = build_domain_results(usable_gold, predictions_df, sample_size=sample_size)
    accepted_warning_count = sum(1 for record in usable_gold if record.get("warning_resolution_status") == "accepted_warning")
    summary, by_task, warning_summary, failure_df = aggregate_domain_results(
        results_df,
        total_gold_count=len(usable_gold) + len(skipped_gold),
        skipped_count=len(skipped_gold),
        accepted_warning_count=accepted_warning_count,
        can_use_false_count=len(skipped_gold),
    )
    write_domain_reports(output_dir, results_df, summary, by_task, failure_df, warning_summary)
    if experiment_meta:
        append_domain_experiment_log(output_dir, experiment_meta, summary, domain_gold_path)
    return DomainEvaluationResult(
        results=results_df,
        summary=summary,
        by_task=by_task,
        warning_summary=warning_summary,
        failure_cases=failure_df,
    )
