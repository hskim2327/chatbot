"""CLI 인자 처리와 전체 평가 실행 흐름을 담당한다."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

import pandas as pd

from .aggregation import aggregate_phase1, build_failure_cases, summarize_ragas
from .config import DEFAULT_EVAL_DIR, DEFAULT_OUTPUT_DIR, OFFICIAL_TOP_K
from .experiment_logger import write_experiment_logs
from .loaders import load_eval_csvs, load_predictions_jsonl, merge_eval_predictions
from .path_utils import project_root, resolve_path
from .ragas_evaluator import run_ragas_evaluation
from .reports import write_dataframe, write_reports
from .retrieval_metrics import evaluate_phase1


def build_arg_parser() -> argparse.ArgumentParser:
    """평가 CLI 인자를 정의한다."""

    parser = argparse.ArgumentParser(description="RAG 평가를 실행합니다.")
    parser.add_argument("--eval-dir", default=DEFAULT_EVAL_DIR, help="eval CSV 파일이 있는 폴더")
    parser.add_argument("--predictions", required=True, help="predictions JSONL 경로")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="평가 결과 출력 폴더")
    parser.add_argument("--canonical-only", action="store_true", help="eval_batch_01~25만 사용")
    parser.add_argument("--top-k", type=int, default=OFFICIAL_TOP_K, help="호환성 옵션. 공식 평가는 top_k=5를 사용")
    parser.add_argument("--experiment-id", default="", help="실험 id. 없으면 자동 생성")
    parser.add_argument("--experiment-name", default="", help="실험 이름")
    parser.add_argument("--notes", default="", help="실험 메모")
    parser.add_argument("--enable-ragas", action="store_true", help="Phase 2 RAGAS 평가 실행")
    parser.add_argument("--require-ragas", action="store_true", help="RAGAS 실패 시 non-zero exit code 반환")
    parser.add_argument("--ragas-sample-size", type=int, default=0, help="RAGAS 평가 샘플 수. 0이면 전체")
    parser.add_argument("--ragas-output-path", default="", help="RAGAS CSV를 별도 저장할 경로")
    parser.add_argument("--include-analysis-metrics", action="store_true", help="doc_recall_at_5 등 분석용 검색 지표를 추가 저장")
    return parser


def collect_experiment_config(predictions_df: pd.DataFrame) -> dict[str, Any]:
    """prediction 첫 행에서 실험 설정 정보를 추출한다."""

    if predictions_df.empty:
        return {}
    row = predictions_df.iloc[0].to_dict()
    retriever_config = row.get("retriever_config") if isinstance(row.get("retriever_config"), dict) else {}
    return {
        "model_name": row.get("model_name", ""),
        "embedding_model": row.get("embedding_model", ""),
        "retriever_type": retriever_config.get("retriever_type", ""),
        "reranker": retriever_config.get("reranker", ""),
        "chunk_size": retriever_config.get("chunk_size", ""),
        "chunk_overlap": retriever_config.get("chunk_overlap", ""),
    }


def build_experiment_meta(args: argparse.Namespace, predictions_path, predictions_df: pd.DataFrame) -> dict[str, Any]:
    """실험 로그에 공통으로 들어갈 메타데이터를 만든다."""

    run_datetime = datetime.now().isoformat(timespec="seconds")
    experiment_id = args.experiment_id or f"{predictions_path.stem}_{run_datetime.replace(':', '').replace('-', '')}"
    return {
        "experiment_id": experiment_id,
        "experiment_name": args.experiment_name,
        "run_datetime": run_datetime,
        "notes": args.notes,
        "predictions_path": str(predictions_path),
        "eval_scope": "canonical_01_25" if args.canonical_only else "all_csv",
        **collect_experiment_config(predictions_df),
    }


def ragas_failed(ragas_metadata: dict[str, Any] | None) -> bool:
    """RAGAS 실패 여부를 strict mode에서 사용할 bool 값으로 변환한다."""

    return bool(ragas_metadata and int(ragas_metadata.get("ragas_error_count", 0)) > 0)


def main(argv: list[str] | None = None) -> int:
    """평가 전체 흐름을 실행하고 exit code를 반환한다."""

    args = build_arg_parser().parse_args(argv)
    if args.require_ragas and not args.enable_ragas:
        print("--require-ragas는 --enable-ragas와 함께 사용해야 합니다.")
        return 2

    root = project_root()
    eval_dir = resolve_path(args.eval_dir, root)
    predictions_path = resolve_path(args.predictions, root)
    output_dir = resolve_path(args.output_dir, root)

    eval_df = load_eval_csvs(eval_dir, canonical_only=args.canonical_only)
    predictions_df = load_predictions_jsonl(predictions_path)
    merged_df = merge_eval_predictions(eval_df, predictions_df)

    phase1_df = evaluate_phase1(
        merged_df,
        top_k=OFFICIAL_TOP_K,
        include_analysis_metrics=args.include_analysis_metrics,
    )
    phase1_summary, by_type, by_difficulty = aggregate_phase1(phase1_df)

    ragas_df = None
    ragas_metadata = None
    ragas_summary = None
    if args.enable_ragas:
        ragas_rows = merged_df.to_dict(orient="records")
        if args.ragas_sample_size and args.ragas_sample_size > 0:
            ragas_rows = ragas_rows[: args.ragas_sample_size]
        ragas_df, ragas_metadata = run_ragas_evaluation(ragas_rows)
        ragas_summary = summarize_ragas(ragas_df)
        if args.ragas_output_path:
            write_dataframe(ragas_df, resolve_path(args.ragas_output_path, root))

    failure_df = build_failure_cases(phase1_df, ragas_df)

    # strict mode에서도 결과 파일을 먼저 저장한 뒤 마지막에 exit code를 결정한다.
    write_reports(output_dir, phase1_df, phase1_summary, by_type, by_difficulty, failure_df, ragas_df, ragas_summary)
    experiment_meta = build_experiment_meta(args, predictions_path, predictions_df)
    write_experiment_logs(
        output_dir,
        experiment_meta,
        phase1_summary,
        by_type,
        by_difficulty,
        ragas_metadata,
        ragas_summary,
        failure_df,
    )

    if args.require_ragas and ragas_failed(ragas_metadata):
        return 2
    return 0

