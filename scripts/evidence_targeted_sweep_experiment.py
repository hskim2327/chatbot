from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evidence_recall_diagnostics as recall_diag
import evidence_selection_expanded_experiment as expanded
import evidence_selection_experiment as base
import evidence_selection_sweep_experiment as sweep


DEFAULT_OUTPUT_DIR = Path("outputs/evidence_recall/targeted_evidence_sweep_experiment")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fact_type(chunk: dict[str, Any]) -> str:
    return base.chunk_fact_type(chunk)


def required_sequence(intents: set[str]) -> list[str]:
    required = expanded.required_fact_types(intents)
    sequence = sweep.fact_sequence_for_intents(intents)
    ranked = [item for item in sequence if item in required]
    extras = sorted(required - set(ranked))
    return ranked + extras


def order_required_first(
    scored: list[tuple[float, dict[str, Any]]],
    intents: set[str],
    scoring: str,
) -> list[tuple[float, dict[str, Any]]]:
    if not scored:
        return []

    by_fact: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for item in scored:
        by_fact.setdefault(fact_type(item[1]), []).append(item)
    for values in by_fact.values():
        values.sort(key=lambda item: (item[0], str(item[1].get("chunk_id") or "")), reverse=True)

    selected: list[tuple[float, dict[str, Any]]] = []
    used_ids: set[str] = set()
    for ft in required_sequence(intents):
        values = by_fact.get(ft) or []
        if not values:
            continue
        score, chunk = values[0]
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id and chunk_id not in used_ids:
            selected.append((score, chunk))
            used_ids.add(chunk_id)

    for score, chunk in sweep.order_chunks(scored, intents, scoring):
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id and chunk_id in used_ids:
            continue
        selected.append((score, chunk))
        if chunk_id:
            used_ids.add(chunk_id)
    return selected


def select_doc_chunks(
    profile: dict[str, Any],
    question: str,
    intents: set[str],
    source_index: dict[str, dict[str, Any]],
    bm25: sweep.BM25Index,
    *,
    scoring: str,
    ordering: str,
    max_per_doc: int,
    seen_ids: set[str],
) -> list[tuple[float, dict[str, Any]]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in profile.get("chunks", []):
        if not base.is_fact_candidate(chunk):
            continue
        chunk_id = str(chunk.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen_ids:
            continue
        score = sweep.score_chunk(chunk, question, intents, source_index, bm25, scoring=scoring)
        if score <= 0:
            continue
        scored.append((score, chunk))

    if ordering == "required_first":
        ordered = order_required_first(scored, intents, scoring)
    elif ordering == "canonical":
        ordered = sweep.order_chunks(scored, intents, "canonical")
    else:
        ordered = sweep.order_chunks(scored, intents, scoring)

    picked = ordered[:max_per_doc]
    for _, chunk in picked:
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id:
            seen_ids.add(chunk_id)
    return picked


def arrange_picks(
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]],
    *,
    policy: str,
    total_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    selected: list[tuple[float, dict[str, Any]]] = []
    used = [0] * len(per_doc_picks)

    def take(doc_idx: int) -> None:
        if used[doc_idx] < len(per_doc_picks[doc_idx]):
            selected.append(per_doc_picks[doc_idx][used[doc_idx]])
            used[doc_idx] += 1

    if policy == "doc_min1_then_score":
        for idx in range(len(per_doc_picks)):
            take(idx)
            if len(selected) >= total_k:
                return selected[:total_k]
        remainder: list[tuple[float, dict[str, Any]]] = []
        for doc_idx, picks in enumerate(per_doc_picks):
            remainder.extend(picks[used[doc_idx] :])
        remainder.sort(key=lambda item: (item[0], str(item[1].get("chunk_id") or "")), reverse=True)
        selected.extend(remainder)
        return selected[:total_k]

    if policy == "doc_min2_then_rr":
        for _ in range(2):
            for idx in range(len(per_doc_picks)):
                take(idx)
                if len(selected) >= total_k:
                    return selected[:total_k]
        return finish_round_robin(per_doc_picks, selected, used, total_k)

    if policy == "adaptive":
        quotas = sweep.quotas_for_docs(len(per_doc_picks), "adaptive")
        for doc_idx, quota in enumerate(quotas):
            for _ in range(quota):
                take(doc_idx)
                if len(selected) >= total_k:
                    return selected[:total_k]
        return finish_round_robin(per_doc_picks, selected, used, total_k)

    if policy == "adaptive_heavy_first":
        quotas = sweep.quotas_for_docs(len(per_doc_picks), "adaptive_heavy_first")
        for doc_idx, quota in enumerate(quotas):
            for _ in range(quota):
                take(doc_idx)
                if len(selected) >= total_k:
                    return selected[:total_k]
        return finish_round_robin(per_doc_picks, selected, used, total_k)

    if policy == "round_robin":
        return finish_round_robin(per_doc_picks, selected, used, total_k)

    if policy == "sequential":
        for doc_idx, picks in enumerate(per_doc_picks):
            while used[doc_idx] < len(picks):
                take(doc_idx)
                if len(selected) >= total_k:
                    return selected[:total_k]
        return selected[:total_k]

    raise ValueError(f"unknown arrange policy: {policy}")


def finish_round_robin(
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]],
    selected: list[tuple[float, dict[str, Any]]],
    used: list[int],
    total_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    max_len = max((len(picks) for picks in per_doc_picks), default=0)
    for offset in range(max_len):
        for doc_idx, picks in enumerate(per_doc_picks):
            if used[doc_idx] <= offset and offset < len(picks):
                selected.append(picks[offset])
                used[doc_idx] = offset + 1
                if len(selected) >= total_k:
                    return selected[:total_k]
    return selected[:total_k]


def select_variant(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    bm25: sweep.BM25Index,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    question = str(row.get("question") or row.get("eval_question") or "")
    intents = base.classify_question_terms(question)
    doc_keys = sweep.candidate_doc_keys(
        row,
        profiles,
        alias_to_primary,
        mode=config["doc_mode"],
        max_docs=config["max_docs"],
    )

    seen_ids: set[str] = set()
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]] = []
    for doc_key in doc_keys:
        profile = profiles.get(doc_key)
        if not profile:
            continue
        picks = select_doc_chunks(
            profile,
            question,
            intents,
            source_index,
            bm25,
            scoring=config["scoring"],
            ordering=config["ordering"],
            max_per_doc=config["max_per_doc"],
            seen_ids=seen_ids,
        )
        if picks:
            per_doc_picks.append(picks)

    arranged = arrange_picks(per_doc_picks, policy=config["arrange_policy"], total_k=config["total_k"])
    return [
        expanded.context_from_chunk(chunk, rank, score, config["variant"], source_index)
        for rank, (score, chunk) in enumerate(arranged[: config["total_k"]], 1)
    ]


def make_rows(
    predictions: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    bm25: sweep.BM25Index,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in predictions:
        selected = select_variant(row, profiles, alias_to_primary, source_index, bm25, config)
        new_row = dict(row)
        new_row["retrieved_contexts_original_count"] = len(row.get("retrieved_contexts") or [])
        new_row["retrieved_contexts"] = selected
        new_row["retrieved_docs"] = base.unique_keep_order(
            [str(item.get("source_file") or item.get("filename") or "") for item in selected]
        )
        new_row["evidence_blocks"] = [
            {
                "source_file": item.get("source_file"),
                "chunk_id": item.get("chunk_id"),
                "rank": item.get("rank"),
                "score": item.get("score"),
                "chunk_type": item.get("metadata", {}).get("chunk_type"),
                "fact_type": item.get("metadata", {}).get("fact_type"),
                "text": item.get("text"),
                "selection_stage": config["variant"],
            }
            for item in selected
        ]
        new_row["evidence_selection_variant"] = config["variant"]
        new_row["evidence_selection_config"] = config
        rows.append(new_row)
    return rows


def score_rows(
    rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    top_k_values: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    predictions_by_id = {str(row.get("id") or ""): row for row in rows}
    diag_rows = [
        recall_diag.make_row(gold_row, predictions_by_id.get(str(gold_row.get("id") or "")), top_k_values)
        for gold_row in gold_rows
    ]
    return recall_diag.summarize(diag_rows, top_k_values), diag_rows


def flatten_summary(config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in config.items() if key != "variant_rows"}
    for key, value in summary.items():
        if key == "diagnosis_counts":
            for diag_key, diag_count in value.items():
                row[diag_key] = diag_count
        elif isinstance(value, float):
            row[key] = round(value, 6)
        else:
            row[key] = value
    return row


def build_configs(args: argparse.Namespace) -> list[dict[str, Any]]:
    doc_modes = [value.strip() for value in args.doc_modes.split(",") if value.strip()]
    scorings = [value.strip() for value in args.scorings.split(",") if value.strip()]
    orderings = [value.strip() for value in args.orderings.split(",") if value.strip()]
    policies = [value.strip() for value in args.arrange_policies.split(",") if value.strip()]
    max_docs_values = [int(value.strip()) for value in args.max_docs_values.split(",") if value.strip()]
    total_k_values = [int(value.strip()) for value in args.total_k_values.split(",") if value.strip()]

    configs: list[dict[str, Any]] = []
    for doc_mode in doc_modes:
        for scoring in scorings:
            for ordering in orderings:
                for policy in policies:
                    for max_docs in max_docs_values:
                        if doc_mode == "existing" and max_docs > 5:
                            continue
                        for total_k in total_k_values:
                            variant = (
                                f"{doc_mode}_{scoring}_{ordering}_{policy}"
                                f"_d{max_docs}_p{args.max_per_doc}_k{total_k}"
                            )
                            configs.append(
                                {
                                    "variant": variant,
                                    "doc_mode": doc_mode,
                                    "scoring": scoring,
                                    "ordering": ordering,
                                    "arrange_policy": policy,
                                    "max_docs": max_docs,
                                    "max_per_doc": args.max_per_doc,
                                    "total_k": total_k,
                                }
                            )
    return configs


def sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        float(row.get("evidence_recall_at_5") or 0),
        float(row.get("evidence_hit_at_5") or 0),
        -float(row.get("doc_hit_but_evidence_missed") or 999),
        float(row.get("context_evidence_recall") or 0),
        float(row.get("doc_recall_at_5") or 0),
    )


def balanced_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(row.get("evidence_hit_at_5") or 0),
        -float(row.get("doc_hit_but_evidence_missed") or 999),
        float(row.get("evidence_recall_at_5") or 0),
        float(row.get("context_evidence_recall") or 0),
    )


def write_summary_md(
    path: Path,
    rows_by_recall: list[dict[str, Any]],
    rows_by_balance: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    lines = [
        "# Targeted Evidence Sweep Experiment",
        "",
        "문서 내부 evidence 재검색, 질문 유형별 fact_type 우선순위, 다중 문서 quota 정책을 함께 비교한 참고용 실험입니다.",
        "",
        f"- output_dir: `{output_dir}`",
        f"- variants: {len(rows_by_recall)}",
        "",
        "## Top 15 by evidence_recall@5",
        "",
        "| rank | variant | evidence_recall@5 | evidence_hit@5 | context_evidence_recall | doc_recall@5 | doc_hit_but_evidence_missed |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(rows_by_recall[:15], 1):
        lines.append(
            f"| {idx} | {row['variant']} | {float(row.get('evidence_recall_at_5', 0)):.4f} | "
            f"{float(row.get('evidence_hit_at_5', 0)):.4f} | "
            f"{float(row.get('context_evidence_recall', 0)):.4f} | "
            f"{float(row.get('doc_recall_at_5', 0)):.4f} | {row.get('doc_hit_but_evidence_missed', 0)} |"
        )

    lines.extend(
        [
            "",
            "## Top 15 by generation-balanced score",
            "",
            "hit@5와 `doc_hit_but_evidence_missed`를 더 중요하게 본 생성 연결용 후보입니다.",
            "",
            "| rank | variant | evidence_recall@5 | evidence_hit@5 | context_evidence_recall | doc_recall@5 | doc_hit_but_evidence_missed |",
            "|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for idx, row in enumerate(rows_by_balance[:15], 1):
        lines.append(
            f"| {idx} | {row['variant']} | {float(row.get('evidence_recall_at_5', 0)):.4f} | "
            f"{float(row.get('evidence_hit_at_5', 0)):.4f} | "
            f"{float(row.get('context_evidence_recall', 0)):.4f} | "
            f"{float(row.get('doc_recall_at_5', 0)):.4f} | {row.get('doc_hit_but_evidence_missed', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- 이 실험은 기존 eval 폴더나 기존 결과를 덮어쓰지 않습니다.",
            "- `required_first`는 질문 유형에 맞는 fact_type을 문서 내부에서 먼저 확보합니다.",
            "- `doc_min1_then_score`, `doc_min2_then_rr`, `adaptive` 계열은 다중 문서 질문에서 한 문서가 top-k를 독점하지 않도록 조절합니다.",
            "- generation에는 raw recall 1등보다 balance 1등 후보를 먼저 붙이는 편이 안정적입니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=base.DEFAULT_PREDICTIONS)
    parser.add_argument("--chunks", type=Path, default=base.DEFAULT_CHUNKS)
    parser.add_argument("--source-store", type=Path, default=expanded.DEFAULT_SOURCE_STORE)
    parser.add_argument("--gold", type=Path, default=base.DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k", default="5,10,20")
    parser.add_argument("--doc-modes", default="existing,existing_then_expanded")
    parser.add_argument("--scorings", default="strict_pack,canonical,hybrid,bm25")
    parser.add_argument("--orderings", default="required_first,canonical,score")
    parser.add_argument("--arrange-policies", default="adaptive,adaptive_heavy_first,round_robin,doc_min1_then_score,doc_min2_then_rr,sequential")
    parser.add_argument("--max-docs-values", default="3,5,7")
    parser.add_argument("--max-per-doc", type=int, default=10)
    parser.add_argument("--total-k-values", default="20,30")
    parser.add_argument("--save-top-n", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k_values = [int(value.strip()) for value in args.top_k.split(",") if value.strip()]
    output_dir = args.output_dir / args.predictions.stem
    top_dir = output_dir / "top_variant_predictions"
    top_dir.mkdir(parents=True, exist_ok=True)

    predictions = base.read_jsonl(args.predictions)
    gold_rows = base.read_jsonl(args.gold)
    chunks = base.load_chunks(args.chunks)
    profiles, alias_to_primary = expanded.load_doc_profiles(chunks)
    source_index = expanded.load_source_store(args.source_store)
    bm25 = sweep.BM25Index(chunks)

    configs = build_configs(args)
    comparison_rows: list[dict[str, Any]] = []
    row_cache: dict[str, list[dict[str, Any]]] = {}
    diag_cache: dict[str, list[dict[str, Any]]] = {}

    baseline_summary, baseline_diag = score_rows(predictions, gold_rows, top_k_values)
    baseline_config = {
        "variant": "baseline_existing_context",
        "doc_mode": "baseline",
        "scoring": "baseline",
        "ordering": "baseline",
        "arrange_policy": "baseline",
        "max_docs": "",
        "max_per_doc": "",
        "total_k": "",
    }
    comparison_rows.append(flatten_summary(baseline_config, baseline_summary))
    row_cache["baseline_existing_context"] = predictions
    diag_cache["baseline_existing_context"] = baseline_diag

    for idx, config in enumerate(configs, 1):
        rows = make_rows(predictions, profiles, alias_to_primary, source_index, bm25, config)
        summary, diag_rows = score_rows(rows, gold_rows, top_k_values)
        comparison_rows.append(flatten_summary(config, summary))
        row_cache[config["variant"]] = rows
        diag_cache[config["variant"]] = diag_rows
        if idx % 50 == 0:
            print(f"scored {idx}/{len(configs)} variants")

    rows_by_recall = sorted(comparison_rows, key=sort_key, reverse=True)
    rows_by_balance = sorted(comparison_rows, key=balanced_key, reverse=True)
    write_csv(output_dir / "comparison_by_recall.csv", rows_by_recall)
    write_csv(output_dir / "comparison_by_balance.csv", rows_by_balance)
    write_summary_md(output_dir / "summary.md", rows_by_recall, rows_by_balance, output_dir)

    saved_variants = base.unique_keep_order(
        [row["variant"] for row in rows_by_recall[: args.save_top_n]]
        + [row["variant"] for row in rows_by_balance[: args.save_top_n]]
    )
    for variant in saved_variants:
        safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", variant)
        write_jsonl(top_dir / f"{safe_name}.jsonl", row_cache[variant])
        recall_diag.write_csv(top_dir / f"{safe_name}_evidence_recall_results.csv", diag_cache[variant])

    print(json.dumps({"by_recall": rows_by_recall[:10], "by_balance": rows_by_balance[:10]}, ensure_ascii=False, indent=2))
    print(f"\nWrote targeted evidence sweep results to {output_dir}")


if __name__ == "__main__":
    main()
