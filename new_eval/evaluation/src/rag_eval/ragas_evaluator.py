"""RAGAS 기본 evaluator 실행을 담당한다."""

from __future__ import annotations

import importlib.metadata
import platform
import sys
from typing import Any

import pandas as pd

from .config import RAGAS_COLUMN_MAP, RAGAS_INPUT_SCHEMA, RAGAS_METRIC_NAMES
from .normalization import retrieved_context_texts


def ragas_version() -> str:
    """설치된 RAGAS 버전을 반환한다."""

    try:
        return importlib.metadata.version("ragas")
    except importlib.metadata.PackageNotFoundError:
        ragas_module = sys.modules.get("ragas")
        return str(getattr(ragas_module, "__version__", "unknown"))


def build_ragas_dataset_dict(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """RAGAS 기본 schema에 맞는 dataset dict를 만든다."""

    return {
        "question": [str(row.get("question") or row.get("question_eval") or "") for row in rows],
        "answer": [str(row.get("answer") or "") for row in rows],
        "contexts": [retrieved_context_texts(row.get("retrieved_contexts")) for row in rows],
        "ground_truth": [str(row.get("ground_truth_answer") or "") for row in rows],
    }


def base_ragas_metadata(error_count: int = 0) -> dict[str, Any]:
    """experiment log에 남길 RAGAS 실행 환경 정보를 만든다."""

    return {
        "ragas_version": ragas_version(),
        "ragas_metrics": ",".join(RAGAS_METRIC_NAMES),
        "ragas_input_schema": RAGAS_INPUT_SCHEMA,
        "ragas_column_map": RAGAS_COLUMN_MAP,
        "ragas_default_evaluator_used": True,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "run_environment": "local",
        "ragas_error_count": error_count,
    }


def run_ragas_evaluation(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """RAGAS evaluate(dataset, metrics=[...]) 기본 호출 방식으로 평가한다."""

    ids = [row.get("id") for row in rows]
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except Exception as exc:
        error_text = f"ragas_import_error: {exc}"
        return pd.DataFrame({"id": ids, "ragas_error": [error_text] * len(rows)}), base_ragas_metadata(len(rows))

    dataset = Dataset.from_dict(build_ragas_dataset_dict(rows))
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    try:
        result = evaluate(dataset, metrics=metrics)
        if hasattr(result, "to_pandas"):
            ragas_df = result.to_pandas()
        else:
            ragas_df = pd.DataFrame(result)
        ragas_df = ragas_df.reset_index(drop=True)
        # RAGAS 버전에 따라 입력 컬럼이 결과에 포함될 수 있으므로, 원문 context 저장을 막기 위해 metric 컬럼만 남긴다.
        allowed_columns = [column for column in RAGAS_METRIC_NAMES if column in ragas_df.columns]
        if "response_relevancy" in ragas_df.columns:
            allowed_columns.append("response_relevancy")
        ragas_df = ragas_df[allowed_columns].copy()
        ragas_df.insert(0, "id", ids[: len(ragas_df)])
        ragas_df["ragas_error"] = ""
        return ragas_df, base_ragas_metadata(0)
    except Exception as exc:
        error_text = f"ragas_evaluate_error: {exc}"
        return pd.DataFrame({"id": ids, "ragas_error": [error_text] * len(rows)}), base_ragas_metadata(len(rows))
