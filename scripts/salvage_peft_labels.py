#!/usr/bin/env python3
"""Conservatively salvage reviewed labels for PEFT/SFT training.

This script does not edit the original ChatGPT label file. It creates a new
salvaged label file and regenerated SFT splits.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_LABELS_PATH = Path("outputs/peft/answer_labels.jsonl")
DEFAULT_OUTPUT_LABELS_PATH = Path("outputs/peft/answer_labels_salvaged_conservative.jsonl")

CONFLICT_KEYWORDS = [
    "충돌",
    "상이",
    "서로 달라",
    "비교 대상",
    "전체의 공통",
    "세 문서",
    "내림차순",
    "해당 레코드에 없",
    "다른 경희대학교",
    "직접 확정하기 어렵",
]

SAFE_MISSING_KEYWORDS = [
    "근거 문장이",
    "근거에서 직접 확인",
    "본문이 제공되지",
    "조건이",
    "기술지원 종료일",
    "원본 제출 여부",
    "운영 수치",
    "기대효과",
    "용수 공급량",
    "외부 교육환경 변화",
    "최근 3년 실적",
    "세부 부수",
    "PG 서버 연동",
    "마감 기준",
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def is_safe_salvage(row: dict[str, Any]) -> tuple[bool, str]:
    if boolish(row.get("trainable")) and not boolish(row.get("needs_human_review")):
        return True, "original_trainable"

    reason = str(row.get("review_reason") or "")
    answer = str(row.get("answer") or "")
    if any(keyword in reason for keyword in CONFLICT_KEYWORDS):
        return False, "excluded_conflict_or_missing_comparison_target"

    is_refusal = "문서에서 확인할 수 없습니다" in answer or "확인되지 않습니다" in answer
    is_partial = "다만" in answer and ("확인되지" in answer or "확정하기 어렵" in answer)
    reason_safe = any(keyword in reason for keyword in SAFE_MISSING_KEYWORDS)

    if reason_safe and (is_refusal or is_partial):
        return True, "salvaged_grounded_refusal_or_partial_answer"

    return False, "still_needs_human_review"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--output-labels-path", type=Path, default=DEFAULT_OUTPUT_LABELS_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.labels_path)
    output_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []

    for row in rows:
        keep, reason = is_safe_salvage(row)
        new_row = dict(row)
        new_row["salvage_status"] = reason
        new_row["salvage_policy"] = "conservative_missing_evidence_only"
        if keep:
            new_row["trainable"] = True
            new_row["needs_human_review"] = False
            if reason != "original_trainable":
                previous = str(new_row.get("review_reason") or "")
                new_row["review_reason"] = (
                    "자동 보수 salvage: 제공 문맥에서 답이 직접 확인되지 않는 grounded refusal/partial answer로 판단. "
                    f"원래 사유: {previous}"
                )
                if str(new_row.get("confidence") or "").lower() == "low":
                    new_row["confidence"] = "medium"
        output_rows.append(new_row)
        report_rows.append(
            {
                "question_id": new_row.get("question_id"),
                "trainable": new_row.get("trainable"),
                "needs_human_review": new_row.get("needs_human_review"),
                "confidence": new_row.get("confidence"),
                "salvage_status": reason,
                "review_reason": new_row.get("review_reason"),
            }
        )

    write_jsonl(args.output_labels_path, output_rows)
    report_path = args.output_labels_path.with_suffix(".report.jsonl")
    write_jsonl(report_path, report_rows)

    counts: dict[str, int] = {}
    for row in report_rows:
        counts[row["salvage_status"]] = counts.get(row["salvage_status"], 0) + 1

    print(f"[OK] wrote labels -> {args.output_labels_path}")
    print(f"[OK] wrote report -> {report_path}")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
