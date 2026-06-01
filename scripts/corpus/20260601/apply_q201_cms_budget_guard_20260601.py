#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TARGET_TITLE = "건설통합시스템(CMS) 고도화"
PROJECT_BUDGET_TEXT = "780,230,000원"
PROJECT_BUDGET_KRW = 780_230_000
NON_PROJECT_AMOUNT_TEXT = "2억원"
NON_PROJECT_AMOUNT_KRW = 200_000_000
TABLE_GUARD = (
    "주의: 이 표의 억 단위 금액은 평가/참여/심사 기준 금액이며 사업예산 답변에 사용하지 않습니다. "
    "이 문서의 사업예산 답변값은 780,230,000원입니다."
)

CHUNK_FILES = [
    ("125", "outputs/parsing_p4_hwpx_125_datafix_goalfix/chunks_v2_125.jsonl"),
    ("125", "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim/chunks_v2_125.jsonl"),
    ("125", "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim/chunks_v2_125_full.jsonl"),
    ("250", "outputs/parsing_p4_hwpx_250_basic/chunks_v2_250.jsonl"),
    ("250", "outputs/parsing_p4_hwpx_250_basic_slim/chunks_v2_250.jsonl"),
    ("250", "outputs/parsing_p4_hwpx_250_basic_slim/chunks_v2_250_full.jsonl"),
    ("690", "outputs/parsing_p4_hwpx_690_basic/chunks_v2_690.jsonl"),
    ("690", "outputs/parsing_p4_hwpx_690_basic_slim/chunks_v2_690.jsonl"),
    ("690", "outputs/parsing_p4_hwpx_690_basic_slim/chunks_v2_690_full.jsonl"),
]

PACKAGE_FOLDERS = [
    ("125", "outputs/parsing_p4_hwpx_125_datafix_goalfix"),
    ("125", "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim"),
    ("250", "outputs/parsing_p4_hwpx_250_basic"),
    ("250", "outputs/parsing_p4_hwpx_250_basic_slim"),
    ("690", "outputs/parsing_p4_hwpx_690_basic"),
    ("690", "outputs/parsing_p4_hwpx_690_basic_slim"),
]


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def sha1_path(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def line_count(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def mib(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def metadata(obj: dict[str, Any]) -> dict[str, Any]:
    md = obj.get("metadata")
    if not isinstance(md, dict):
        md = {}
        obj["metadata"] = md
    return md


def field(obj: dict[str, Any], key: str) -> Any:
    md = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    return obj.get(key) if obj.get(key) not in (None, "") else md.get(key, "")


def is_false_value(value: Any) -> bool:
    return value is False or str(value).strip().lower() == "false"


def is_target_doc(obj: dict[str, Any]) -> bool:
    md = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    values = [
        obj.get("source_file", ""),
        obj.get("doc_key", ""),
        obj.get("canonical_doc_key", ""),
        obj.get("project_name", ""),
        md.get("source_file", ""),
        md.get("doc_key", ""),
        md.get("canonical_doc_key", ""),
        md.get("project_name", ""),
        obj.get("content", "")[:500],
    ]
    return any(TARGET_TITLE in str(value) for value in values)


def set_field(obj: dict[str, Any], key: str, value: Any) -> bool:
    changed = False
    if key in obj and obj.get(key) != value:
        obj[key] = value
        changed = True
    md = metadata(obj)
    if md.get(key) != value:
        md[key] = value
        changed = True
    return changed


def replace_common_text(text: str) -> str:
    text = text.replace(
        "공고문 기초금액: 2억원 | 실제 사업예산: 미기재 또는 비공개 | 예산 역할: notice_base_amount",
        "실제 사업예산/배정예산: 780,230,000원(나라장터 bgtAmt) | 공고문 기초금액/추정가격 2억원은 사업예산 답변 금지 | 예산 역할: project_budget",
    )
    text = text.replace(
        "사업금액: 780,230,000원(나라장터 통합공고 상세 bgtAmt 근거; 원문 사업예산 미기재)|",
        "사업금액: 780,230,000원(나라장터 통합공고 상세 bgtAmt 근거; 원문 사업예산 미기재; 2억원은 추정가격/기초금액으로 사업예산 답변 금지)|",
    )
    return text


def fix_document_summary(obj: dict[str, Any]) -> bool:
    changed = False
    for key, value in {
        "final_budget": PROJECT_BUDGET_TEXT,
        "final_budget_krw": str(PROJECT_BUDGET_KRW),
        "final_budget_status": "g2b_verified",
        "budget_value_role": "project_budget",
        "amount_raw": PROJECT_BUDGET_TEXT,
        "amount_krw": PROJECT_BUDGET_KRW,
        "amount_type": "project_budget",
        "budget_type": "project_budget",
        "answer_policy": "route_only_not_final_answer",
        "budget_answer_enabled": False,
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": False,
    }.items():
        changed = set_field(obj, key, value) or changed

    for text_key in ("content", "evidence_text_short"):
        if isinstance(obj.get(text_key), str):
            new_text = replace_common_text(obj[text_key])
            if new_text != obj[text_key]:
                obj[text_key] = new_text
                changed = True
    md = metadata(obj)
    if isinstance(md.get("evidence_text_short"), str):
        new_text = replace_common_text(md["evidence_text_short"])
        if new_text != md["evidence_text_short"]:
            md["evidence_text_short"] = new_text
            changed = True
    return changed


def fix_non_project_amount_fact(obj: dict[str, Any]) -> bool:
    changed = False
    fact_type = str(field(obj, "fact_type") or "")
    amount_krw = field(obj, "amount_krw")
    is_two_eok = amount_krw in {NON_PROJECT_AMOUNT_KRW, str(NON_PROJECT_AMOUNT_KRW)} or NON_PROJECT_AMOUNT_TEXT in str(obj.get("content", ""))
    if not (fact_type in {"estimated_price", "threshold_budget"} or is_two_eok):
        return False

    if fact_type == "estimated_price":
        if obj.get("fact_type") == "estimated_price":
            obj["fact_type"] = "reference_amount"
            changed = True
        md = metadata(obj)
        if md.get("fact_type") == "estimated_price":
            md["fact_type"] = "reference_amount"
            changed = True
        for key, value in {
            "amount_raw": NON_PROJECT_AMOUNT_TEXT,
            "amount_krw": NON_PROJECT_AMOUNT_KRW,
            "amount_type": "estimated_price_not_project_budget",
            "budget_type": "estimated_price_not_project_budget",
            "answer_policy": "route_only_not_final_answer",
            "budget_answer_enabled": False,
            "eligibility_answer_enabled": False,
            "payment_answer_enabled": False,
        }.items():
            changed = set_field(obj, key, value) or changed
        replacement = (
            "사업예산 답변값은 780,230,000원입니다. "
            "2억원은 추정가격/기초금액으로, 사업예산/사업금액 답변에 사용하지 않습니다. "
            "추정가격/보조금액: 2억원 | KRW: 200000000 | budget_type: estimated_price_not_project_budget | "
            "실제 사업예산/전체 배정액은 나라장터 통합공고 상세 bgtAmt 780,230,000원 fact를 사용"
        )
        old = (
            "추정가격/보조금액(최종 사업예산 답변 금지): 2억원 | KRW: 200000000 | "
            "budget_type: estimated_price | 실제 사업예산/전체 배정액은 원문이 아니라 "
            "나라장터 통합공고 상세 bgtAmt 780,230,000원 fact를 사용"
        )
        for text_key in ("content", "evidence_text_short"):
            if isinstance(obj.get(text_key), str):
                new_text = obj[text_key].replace("핵심 후보 정보 > estimated_price", "핵심 후보 정보 > reference_amount").replace(old, replacement)
                if new_text != obj[text_key]:
                    obj[text_key] = new_text
                    changed = True
    elif fact_type == "threshold_budget":
        for key, value in {
            "answer_policy": "allow_for_eligibility_exclude_for_project_budget",
            "budget_answer_enabled": False,
            "eligibility_answer_enabled": True,
        }.items():
            changed = set_field(obj, key, value) or changed
    return changed


def table_or_text_has_risky_amount(obj: dict[str, Any]) -> bool:
    if str(field(obj, "chunk_type")) not in {"table", "text"}:
        return False
    content = str(obj.get("content") or "")
    if "억원" not in content and "억" not in content:
        return False
    return any(token in content for token in ["평가", "심사", "참여", "기준", "추정가격", "15억원", "20억원", "25억원", "2억원"])


def insert_guard(content: str) -> str:
    if TABLE_GUARD in content:
        return content
    if content.startswith("[문서:") and "\n" in content:
        first, rest = content.split("\n", 1)
        return f"{first}\n{TABLE_GUARD}\n{rest}"
    return f"{TABLE_GUARD}\n{content}"


def fix_table_or_text(obj: dict[str, Any]) -> bool:
    if not table_or_text_has_risky_amount(obj):
        return False
    changed = False
    content = str(obj.get("content") or "")
    if TABLE_GUARD not in content and PROJECT_BUDGET_TEXT not in content:
        obj["content"] = insert_guard(content)
        changed = True
    for key, value in {
        "answer_policy": "allow_as_evaluation_threshold_exclude_for_project_budget",
        "answer_risk_level": "high",
        "answer_allowed_question_types": "eligibility,performance_requirement,general_reference",
        "answer_blocked_question_types": "budget,project_budget,total_allocation,budget_difference,budget_sum",
        "budget_answer_enabled": False,
        "payment_answer_enabled": False,
        "budget_value_role": "evaluation_or_review_threshold_not_project_budget",
        "amount_type": "evaluation_or_review_threshold_not_project_budget",
        "budget_policy_note": "이 청크의 억 단위 금액은 평가/참여/심사 기준 금액이며, 사업예산 답변에는 G2B 검증 사업예산 780,230,000원을 사용.",
    }.items():
        changed = set_field(obj, key, value) or changed
    return changed


def fix_row(obj: dict[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    if not is_target_doc(obj):
        return obj, False, None
    fact_type = str(field(obj, "fact_type") or "")
    if fact_type == "document_summary":
        return obj, fix_document_summary(obj), "document_summary_budget_role"
    if fix_non_project_amount_fact(obj):
        return obj, True, "non_project_amount_guard"
    if fix_table_or_text(obj):
        return obj, True, "table_or_text_amount_guard"
    return obj, False, None


def scan_file(path: Path) -> dict[str, Any]:
    summary = {
        "target_rows": 0,
        "project_budget_rows": 0,
        "bad_summary_rows": 0,
        "bad_estimated_price_rows": 0,
        "unguarded_table_amount_rows": 0,
        "wrong_guard_metadata_rows": 0,
        "would_change_rows": 0,
        "reasons": {},
    }
    if not path.exists():
        summary["missing"] = True
        return summary
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if not is_target_doc(obj):
                continue
            summary["target_rows"] += 1
            fact_type = str(field(obj, "fact_type") or "")
            chunk_type = str(field(obj, "chunk_type") or "")
            content = str(obj.get("content") or "")
            if fact_type == "project_budget" and (PROJECT_BUDGET_TEXT in content or str(field(obj, "final_budget_krw")) == str(PROJECT_BUDGET_KRW)):
                summary["project_budget_rows"] += 1
            if fact_type == "document_summary" and not (str(field(obj, "final_budget_krw")) == str(PROJECT_BUDGET_KRW) and field(obj, "amount_type") == "project_budget"):
                summary["bad_summary_rows"] += 1
            if fact_type == "estimated_price":
                summary["bad_estimated_price_rows"] += 1
            if chunk_type in {"table", "text"} and any(token in content for token in ["2억원", "15억원", "20억원", "25억원"]):
                if TABLE_GUARD not in content:
                    summary["unguarded_table_amount_rows"] += 1
                elif not is_false_value(field(obj, "budget_answer_enabled")) or field(obj, "budget_value_role") != "evaluation_or_review_threshold_not_project_budget":
                    summary["wrong_guard_metadata_rows"] += 1
            _, changed, reason = fix_row(json.loads(line))
            if changed:
                summary["would_change_rows"] += 1
                summary["reasons"][reason or "unknown"] = summary["reasons"].get(reason or "unknown", 0) + 1
    return summary


def update_chunks(path: Path) -> dict[str, Any]:
    before = scan_file(path)
    if not path.exists():
        return {"file": str(path), "missing": True, "before": before, "changed_rows": 0}
    tmp = path.with_suffix(path.suffix + ".tmp")
    changed_rows = 0
    reasons: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            obj = json.loads(line)
            obj, changed, reason = fix_row(obj)
            if changed:
                changed_rows += 1
                reasons[reason or "unknown"] = reasons.get(reason or "unknown", 0) + 1
            dst.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    after = scan_file(path)
    return {"file": str(path), "before": before, "after": after, "changed_rows": changed_rows, "reasons": reasons}


def refresh_report_and_manifest(folder: Path, suffix: str) -> None:
    runtime = folder / f"chunks_v2_{suffix}.jsonl"
    detailed = folder / f"chunks_v2_{suffix}_full.jsonl"
    validation = folder / "validation_report_v2.json"
    if validation.exists() and runtime.exists():
        report = json.loads(validation.read_text(encoding="utf-8"))
        report["chunks_jsonl_sha1"] = sha1_path(runtime)
        report["chunks_jsonl_file_size_mib"] = round(mib(runtime), 2)
        report["chunks_jsonl_line_count"] = line_count(runtime)
        if detailed.exists():
            report["detailed_chunks_jsonl_sha1"] = sha1_path(detailed)
            report["detailed_chunks_jsonl_file_size_mib"] = round(mib(detailed), 2)
            report["detailed_chunks_jsonl_line_count"] = line_count(detailed)
        report["q201_cms_budget_guard_20260601"] = {
            "status": "applied",
            "target": TARGET_TITLE,
            "project_budget": PROJECT_BUDGET_TEXT,
            "policy": "2억원 등 억 단위 평가/심사/참여 기준 금액은 사업예산 답변에서 제외",
        }
        report["updated_at"] = datetime.now(timezone.utc).isoformat()
        validation.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = folder / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data.setdefault("file_hashes", {})
        targets = {
            "chunks_v2_sha1": runtime,
            "chunks_v2_full_sha1": detailed,
            "validation_v2_sha1": validation,
        }
        for key, target in targets.items():
            if target.exists():
                data["file_hashes"][key] = sha1_path(target)
        data["q201_cms_budget_guard_20260601"] = {"status": "applied"}
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply or check Q201 CMS budget role guard for P4 corpus packages.")
    parser.add_argument("--project-root", type=Path, default=default_project_root(), help="Repository/project root containing outputs/.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Modify chunk files and refresh manifest/validation hashes.")
    mode.add_argument("--check", action="store_true", help="Only scan current files. This is the default.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    apply_changes = bool(args.apply)

    results = []
    for _, rel in CHUNK_FILES:
        path = project_root / rel
        if apply_changes:
            results.append(update_chunks(path))
        else:
            results.append({"file": str(path), "check": scan_file(path)})

    if apply_changes:
        for suffix, rel in PACKAGE_FOLDERS:
            refresh_report_and_manifest(project_root / rel, suffix)

    print(json.dumps({"mode": "apply" if apply_changes else "check", "project_root": str(project_root), "results": results}, ensure_ascii=False, indent=2))

    failed = False
    for item in results:
        summary = item.get("after") or item.get("check") or {}
        if summary.get("missing"):
            continue
        if summary.get("project_budget_rows", 0) < 1:
            failed = True
        for key in ("bad_summary_rows", "bad_estimated_price_rows", "unguarded_table_amount_rows", "wrong_guard_metadata_rows"):
            if summary.get(key, 0):
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
