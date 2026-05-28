"""append-only 실험 로그 저장을 담당한다."""

from __future__ import annotations

import csv
import json
from typing import Any

import pandas as pd

from .config import FAILURE_EXPERIMENT_LOG, OFFICIAL_TOP_K, PHASE1_EXPERIMENT_LOG, PHASE2_EXPERIMENT_LOG
from .path_utils import ensure_parent

def _fieldnames_for_append(path, fallback: list[str]) -> list[str]:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        try:
            header = next(reader)
        except StopIteration:
            return fallback
    return header or fallback


def append_experiment_log(path, row: dict[str, Any]) -> None:
    """기존 CSV를 덮어쓰지 않고 실험 로그 한 행을 추가한다."""

    ensure_parent(path)
    serializable = {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        for key, value in row.items()
    }
    file_exists = path.exists()
    fieldnames = _fieldnames_for_append(path, list(serializable.keys()))
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(serializable)


def write_experiment_logs(
    output_dir,
    experiment_meta: dict[str, Any],
    phase1_summary: dict[str, Any],
    by_type: pd.DataFrame,
    by_difficulty: pd.DataFrame,
    ragas_metadata: dict[str, Any] | None,
    ragas_summary: dict[str, Any] | None,
    failure_df: pd.DataFrame,
) -> None:
    """Phase 1, RAGAS, failure analysis 실험 로그를 append한다."""

    log_dir = output_dir / "experiment_logs"
    common = {
        "experiment_id": experiment_meta["experiment_id"],
        "experiment_name": experiment_meta.get("experiment_name", ""),
        "run_datetime": experiment_meta["run_datetime"],
        "notes": experiment_meta.get("notes", ""),
    }
    append_experiment_log(
        log_dir / PHASE1_EXPERIMENT_LOG,
        {
            **common,
            "predictions_path": experiment_meta.get("predictions_path", ""),
            "eval_scope": experiment_meta.get("eval_scope", ""),
            "model_name": experiment_meta.get("model_name", ""),
            "embedding_model": experiment_meta.get("embedding_model", ""),
            "retriever_type": experiment_meta.get("retriever_type", ""),
            "reranker": experiment_meta.get("reranker", ""),
            "chunk_size": experiment_meta.get("chunk_size", ""),
            "chunk_overlap": experiment_meta.get("chunk_overlap", ""),
            "top_k": OFFICIAL_TOP_K,
            **phase1_summary,
            "by_type_summary_json": by_type.to_json(orient="records", force_ascii=False),
            "by_difficulty_summary_json": by_difficulty.to_json(orient="records", force_ascii=False),
        },
    )

    if ragas_metadata is not None:
        append_experiment_log(
            log_dir / PHASE2_EXPERIMENT_LOG,
            {
                **common,
                **ragas_metadata,
                **(ragas_summary or {}),
            },
        )

    reasons = failure_df.get("failure_reason", pd.Series(dtype=str)).astype(str)
    append_experiment_log(
        log_dir / FAILURE_EXPERIMENT_LOG,
        {
            **common,
            "num_failure_cases": int(len(failure_df)),
            "num_retrieval_failures": int(reasons.eq("retrieval_failure").sum()),
            "num_ragas_errors": int(reasons.eq("ragas_error").sum()),
            "failure_cases_path": str(output_dir / "failure_cases.csv"),
        },
    )

