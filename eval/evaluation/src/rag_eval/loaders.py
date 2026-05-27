"""eval CSV와 prediction JSONL 로딩을 담당한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import CANONICAL_BATCH_END, CANONICAL_BATCH_START, EVAL_REQUIRED_COLUMNS, PREDICTION_REQUIRED_COLUMNS
from .normalization import parse_doc_list, parse_structured_cell


def load_eval_csvs(eval_dir: Path, canonical_only: bool = True) -> pd.DataFrame:
    """eval CSV를 읽고 내부 평가에 필요한 파생 컬럼을 추가한다."""

    if canonical_only:
        csv_paths = [eval_dir / f"eval_batch_{idx:02d}.csv" for idx in range(CANONICAL_BATCH_START, CANONICAL_BATCH_END + 1)]
        missing = [str(path) for path in csv_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing canonical eval CSV files: {missing}")
    else:
        csv_paths = sorted(eval_dir.glob("*.csv"))
        if not csv_paths:
            raise FileNotFoundError(f"No eval CSV files found under {eval_dir}")

    frames = []
    for csv_path in csv_paths:
        frame = pd.read_csv(csv_path)
        frame["source_eval_file"] = csv_path.name
        frames.append(frame)

    eval_df = pd.concat(frames, ignore_index=True)
    missing_columns = [column for column in EVAL_REQUIRED_COLUMNS if column not in eval_df.columns]
    if missing_columns:
        raise ValueError(f"Eval CSV is missing required columns: {missing_columns}")

    duplicated_ids = eval_df[eval_df["id"].duplicated(keep=False)][["id", "source_eval_file"]]
    if not duplicated_ids.empty:
        duplicate_sample = (
            duplicated_ids.groupby("id")["source_eval_file"]
            .apply(lambda values: sorted(set(values))[:5])
            .head(10)
            .to_dict()
        )
        raise ValueError(
            "Eval CSV contains duplicated question ids across files. "
            f"Sample: {duplicate_sample}. "
            "Use --canonical-only for eval_batch_01~25 or move non-canonical files out of the eval directory."
        )

    eval_df["ground_truth_doc_list"] = eval_df["ground_truth_docs"].apply(parse_doc_list)
    eval_df["metadata_filter_obj"] = eval_df["metadata_filter"].apply(lambda value: parse_structured_cell(value, {}))
    eval_df["history_obj"] = eval_df["history"].apply(lambda value: parse_structured_cell(value, []))
    eval_df["has_history"] = eval_df["history_obj"].apply(bool)
    eval_df["is_multi_doc"] = eval_df["ground_truth_doc_list"].apply(lambda docs: len(docs) > 1)
    eval_df["is_unanswerable"] = eval_df["type"].astype(str).str.upper().eq("D")
    eval_df["normalized_type"] = eval_df["type"].astype(str).str.strip().str.upper()
    eval_df["normalized_difficulty"] = eval_df["difficulty"].astype(str).str.strip()
    return eval_df


def load_predictions_jsonl(predictions_path: Path) -> pd.DataFrame:
    """RAG 시스템 출력 predictions JSONL을 읽는다."""

    rows: list[dict[str, Any]] = []
    with predictions_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc

    predictions_df = pd.DataFrame(rows)
    missing_columns = [column for column in PREDICTION_REQUIRED_COLUMNS if column not in predictions_df.columns]
    if missing_columns:
        raise ValueError(f"Predictions JSONL is missing required fields: {missing_columns}")
    return predictions_df


def merge_eval_predictions(eval_df: pd.DataFrame, predictions_df: pd.DataFrame) -> pd.DataFrame:
    """eval과 prediction을 id 기준으로 병합한다."""

    merged = eval_df.merge(
        predictions_df,
        on="id",
        how="left",
        suffixes=("_eval", "_pred"),
        indicator=True,
    )
    merged["prediction_missing"] = merged["_merge"].ne("both")
    return merged.drop(columns=["_merge"])

