"""CLI 인자 처리와 전체 평가 실행 흐름을 관리한다."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

import pandas as pd

from .aggregation import aggregate_phase1, build_failure_cases, summarize_ragas
from .config import DEFAULT_DOMAIN_GOLD_PATH, DEFAULT_EVAL_DIR, DEFAULT_OUTPUT_DIR, OFFICIAL_TOP_K
from .domain_runner import run_domain_evaluation
from .experiment_logger import write_experiment_logs
from .loaders import load_eval_csvs, load_predictions_jsonl, merge_eval_predictions
from .llm_judge_runner import run_llm_judge_evaluation
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
    parser.add_argument("--top-k", type=int, default=OFFICIAL_TOP_K, help="호환용 옵션. 공식 평가는 top_k=5를 사용")
    parser.add_argument("--experiment-id", default="", help="실험 id. 없으면 자동 생성")
    parser.add_argument("--experiment-name", default="", help="실험 이름")
    parser.add_argument("--notes", default="", help="실험 메모")
    parser.add_argument("--enable-ragas", action="store_true", help="Phase 2 RAGAS 평가 실행")
    parser.add_argument("--require-ragas", action="store_true", help="RAGAS 실패 시 non-zero exit code 반환")
    parser.add_argument("--ragas-sample-size", type=int, default=0, help="RAGAS 평가 샘플 수. 0이면 전체")
    parser.add_argument("--ragas-output-path", default="", help="RAGAS CSV를 별도 저장할 경로")
    parser.add_argument("--enable-domain", action="store_true", help="Phase 3 RFP 도메인 평가 실행")
    parser.add_argument("--require-domain", action="store_true", help="Phase 3 실패 시 가능한 결과 저장 후 non-zero 반환")
    parser.add_argument("--domain-gold-path", default=DEFAULT_DOMAIN_GOLD_PATH, help="Phase 3 도메인 gold JSONL 경로")
    parser.add_argument("--domain-output-dir", default="", help="Phase 3 결과 출력 폴더. 비우면 --output-dir 사용")
    parser.add_argument("--domain-sample-size", type=int, default=0, help="Phase 3 평가 샘플 수. 0이면 전체")
    parser.add_argument("--enable-llm-judge", action="store_true", help="Phase 4 LLM Judge 평가 실행")
    parser.add_argument("--llm-judge-mode", choices=("mock", "dry_run", "api"), default="mock", help="LLM Judge 실행 모드")
    parser.add_argument(
        "--llm-judge-reference-mode",
        choices=("evidence_only", "gold_guided"),
        default="evidence_only",
        help="LLM Judge 입력 참조 방식. 기본값은 evidence_only",
    )
    parser.add_argument("--llm-judge-model", default="", help="LLM Judge 모델명. API key 값은 기록하지 않음")
    parser.add_argument("--llm-judge-sample-size", type=int, default=0, help="LLM Judge 샘플 수. 0이면 전체")
    parser.add_argument("--llm-judge-output-dir", default="", help="LLM Judge 결과 출력 폴더. 비우면 --output-dir 사용")
    parser.add_argument("--llm-judge-dry-run", action="store_true", help="API 호출 없이 judge input JSONL만 생성")
    parser.add_argument("--require-llm-judge", action="store_true", help="LLM Judge 실패 시 가능한 결과 저장 후 non-zero 반환")
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


def write_domain_error_summary(output_dir, error: Exception) -> None:
    """Phase 3 실패 내용을 짧은 Markdown 파일로 남긴다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 3 RFP 도메인 평가 오류",
        "",
        "Phase 3 실행 중 오류가 발생했습니다. Phase 1/2 결과 저장은 이 오류와 분리됩니다.",
        "",
        f"- error_type: {type(error).__name__}",
        f"- error: {error}",
    ]
    (output_dir / "phase3_domain_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_llm_judge_error_summary(output_dir, error: Exception) -> None:
    """Phase 4 실패 내용을 짧은 Markdown 파일로 남긴다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 4 LLM Judge 평가 오류",
        "",
        "Phase 4 실행 중 오류가 발생했습니다. Phase 1/2/3 결과 저장은 이 오류와 분리됩니다.",
        "",
        f"- error_type: {type(error).__name__}",
        f"- error: {error}",
    ]
    (output_dir / "phase4_llm_judge_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """평가 전체 흐름을 실행하고 exit code를 반환한다."""

    args = build_arg_parser().parse_args(argv)
    if args.require_ragas and not args.enable_ragas:
        print("--require-ragas는 --enable-ragas와 함께 사용해야 합니다.")
        return 2
    if args.require_domain and not args.enable_domain:
        print("--require-domain은 --enable-domain과 함께 사용해야 합니다.")
        return 2
    if args.require_llm_judge and not args.enable_llm_judge:
        print("--require-llm-judge는 --enable-llm-judge와 함께 사용해야 합니다.")
        return 2

    root = project_root()
    eval_dir = resolve_path(args.eval_dir, root)
    predictions_path = resolve_path(args.predictions, root)
    output_dir = resolve_path(args.output_dir, root)

    eval_df = load_eval_csvs(eval_dir, canonical_only=args.canonical_only)
    predictions_df = load_predictions_jsonl(predictions_path)
    merged_df = merge_eval_predictions(eval_df, predictions_df)

    phase1_df = evaluate_phase1(merged_df, top_k=OFFICIAL_TOP_K)
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

    domain_failed = False
    if args.enable_domain:
        domain_output_dir = resolve_path(args.domain_output_dir, root) if args.domain_output_dir else output_dir
        domain_gold_path = resolve_path(args.domain_gold_path, root)
        try:
            run_domain_evaluation(
                domain_gold_path,
                predictions_df,
                domain_output_dir,
                experiment_meta=experiment_meta,
                sample_size=args.domain_sample_size,
            )
        except Exception as exc:
            domain_failed = True
            write_domain_error_summary(domain_output_dir, exc)
            print(f"Phase 3 domain evaluation failed: {exc}")

    llm_judge_failed = False
    if args.enable_llm_judge:
        llm_output_dir = resolve_path(args.llm_judge_output_dir, root) if args.llm_judge_output_dir else output_dir
        domain_gold_path = resolve_path(args.domain_gold_path, root)
        llm_mode = "dry_run" if args.llm_judge_dry_run else args.llm_judge_mode
        try:
            run_llm_judge_evaluation(
                predictions_df=predictions_df,
                domain_gold_path=domain_gold_path,
                output_dir=llm_output_dir,
                experiment_meta=experiment_meta,
                mode=llm_mode,
                reference_mode=args.llm_judge_reference_mode,
                model=args.llm_judge_model,
                sample_size=args.llm_judge_sample_size,
            )
        except Exception as exc:
            llm_judge_failed = True
            write_llm_judge_error_summary(llm_output_dir, exc)
            print(f"Phase 4 LLM Judge evaluation failed: {exc}")

    if args.require_ragas and ragas_failed(ragas_metadata):
        return 2
    if args.require_domain and domain_failed:
        return 3
    if args.require_llm_judge and llm_judge_failed:
        return 4
    return 0
