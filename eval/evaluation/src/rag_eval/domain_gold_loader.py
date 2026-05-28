"""Phase 3 RFP 도메인 gold JSONL 로딩을 담당한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_domain_gold(gold_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """도메인 gold JSONL을 읽고 Phase 3 사용 가능 record와 제외 record를 나눈다.

    `can_use_for_phase3=false`인 문항은 평가에서 제외한다. 다만
    `warning_resolution_status=accepted_warning`인 문항은 해석 주의 대상일 뿐,
    평가 대상에서 제외하지 않는다.
    """

    if not gold_path.exists():
        raise FileNotFoundError(f"Domain gold JSONL not found: {gold_path}")

    usable_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with gold_path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid domain gold JSONL at line {line_number}: {exc}") from exc

            record_id = str(record.get("id", "")).strip()
            if not record_id:
                raise ValueError(f"Domain gold record at line {line_number} has no id")
            if record_id in seen_ids:
                raise ValueError(f"Duplicate domain gold id: {record_id}")
            seen_ids.add(record_id)

            if record.get("can_use_for_phase3") is False:
                skipped_records.append(record)
            else:
                usable_records.append(record)

    return usable_records, skipped_records


def required_gold_block_name(task_family: str) -> str:
    """task_family에 대응하는 gold block 이름을 반환한다."""

    mapping = {
        "budget": "budget_gold",
        "required_fields": "required_field_gold",
        "submission_eligibility_deadline": "submission_eligibility_deadline_gold",
        "unanswerable": "unanswerable_gold",
        "multi_doc_comparison": "multi_doc_comparison_gold",
        "robust_query_type_e": "robust_query_gold",
    }
    return mapping.get(task_family, "")
