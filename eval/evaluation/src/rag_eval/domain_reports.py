"""Phase 3 도메인 평가 결과 파일 저장을 담당한다."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .reports import write_dataframe, write_json
from .path_utils import ensure_dir, ensure_parent, safe_json_value


def write_domain_summary_markdown(path, summary: dict[str, Any], warning_summary: dict[str, Any]) -> None:
    """Phase 3 도메인 평가 요약을 Markdown으로 저장한다."""

    ensure_parent(path)
    lines = [
        "# Phase 3 RFP 도메인 평가 요약",
        "",
        "## 전체 요약",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Warning 요약", ""])
    for key, value in warning_summary.items():
        lines.append(f"- {key}: {value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_domain_reports(
    output_dir,
    results_df: pd.DataFrame,
    summary: dict[str, Any],
    by_task: pd.DataFrame,
    failure_df: pd.DataFrame,
    warning_summary: dict[str, Any],
) -> None:
    """Phase 3 도메인 평가 산출물을 가능한 범위까지 모두 저장한다."""

    ensure_dir(output_dir)
    write_dataframe(results_df, output_dir / "phase3_domain_results.csv")
    write_json([safe_json_value(row) for row in results_df.to_dict(orient="records")], output_dir / "phase3_domain_results.json")
    write_dataframe(by_task, output_dir / "phase3_domain_by_task.csv")
    write_dataframe(failure_df, output_dir / "phase3_domain_failure_cases.csv")
    write_domain_summary_markdown(output_dir / "phase3_domain_summary.md", summary, warning_summary)
