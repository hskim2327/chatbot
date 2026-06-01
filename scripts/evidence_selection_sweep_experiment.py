from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evidence_recall_diagnostics as recall_diag
import evidence_selection_expanded_experiment as expanded
import evidence_selection_experiment as base


DEFAULT_OUTPUT_DIR = Path("outputs/evidence_recall/evidence_selection_sweep_experiment")


TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
QUERY_EXPANSIONS = {
    "budget": [
        "사업예산",
        "사업금액",
        "사업비",
        "총사업비",
        "예산금액",
        "배정예산",
        "project_budget",
        "final_budget",
        "KRW",
    ],
    "date": [
        "사업기간",
        "계약기간",
        "수행기간",
        "입찰마감",
        "제출마감",
        "유지보수",
        "하자",
        "project_duration",
        "deadline",
    ],
    "submission": ["제출서류", "구비서류", "제안서", "서식", "submission_documents"],
    "eligibility": ["참가자격", "입찰자격", "공동수급", "실적", "eligibility"],
    "summary": ["문서요약", "사업개요", "요구사항", "사업유형", "document_summary"],
}


FACT_SEQUENCE = {
    "budget": [
        "document_identity",
        "document_summary",
        "project_budget",
        "budget",
        "estimated_price",
        "base_amount",
        "business_type",
        "requirements",
        "submission_documents",
        "eligibility",
    ],
    "date": [
        "document_identity",
        "document_summary",
        "project_duration",
        "duration",
        "bid_deadline",
        "submission_deadline",
        "maintenance_period",
        "warranty_period",
    ],
    "submission": [
        "document_identity",
        "submission_documents",
        "submission_logistics",
        "document_summary",
    ],
    "eligibility": [
        "document_identity",
        "eligibility",
        "requirements",
        "threshold_budget",
        "document_summary",
    ],
    "summary": [
        "document_identity",
        "document_summary",
        "business_type",
        "requirements",
    ],
    "general": [
        "document_identity",
        "document_summary",
        "business_type",
        "requirements",
    ],
}


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in TOKEN_RE.findall(text or ""):
        token = token.lower()
        if token in expanded.STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def query_tokens(question: str, intents: set[str]) -> list[str]:
    terms = tokenize(question)
    for intent in intents:
        terms.extend(tokenize(" ".join(QUERY_EXPANSIONS.get(intent, []))))
    return base.unique_keep_order(terms)


class BM25Index:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunk_tokens: dict[str, list[str]] = {}
        self.doc_freq: Counter[str] = Counter()
        self.doc_len: dict[str, int] = {}
        for chunk in chunks:
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id or not base.is_fact_candidate(chunk):
                continue
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            text = " ".join(
                [
                    str(chunk.get("text") or ""),
                    str(metadata.get("section_path") or ""),
                    str(metadata.get("project_name") or ""),
                    str(metadata.get("issuer") or ""),
                ]
            )
            tokens = tokenize(text)
            self.chunk_tokens[chunk_id] = tokens
            self.doc_len[chunk_id] = len(tokens)
            self.doc_freq.update(set(tokens))
        self.n_docs = max(len(self.chunk_tokens), 1)
        self.avg_len = sum(self.doc_len.values()) / max(len(self.doc_len), 1)

    def score(self, chunk: dict[str, Any], terms: list[str]) -> float:
        chunk_id = str(chunk.get("chunk_id") or "")
        tokens = self.chunk_tokens.get(chunk_id, [])
        if not tokens or not terms:
            return 0.0
        counts = Counter(tokens)
        dl = self.doc_len.get(chunk_id, len(tokens))
        k1 = 1.5
        b = 0.75
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf <= 0:
                continue
            df = self.doc_freq.get(term, 0)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * dl / max(self.avg_len, 1e-9))
            score += idf * (tf * (k1 + 1) / denom)
        return score


def existing_doc_keys(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    max_docs: int,
) -> list[str]:
    return expanded.existing_doc_keys(row, profiles, alias_to_primary, max_docs=max_docs)


def candidate_doc_keys(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    *,
    mode: str,
    max_docs: int,
) -> list[str]:
    if mode == "existing":
        return existing_doc_keys(row, profiles, alias_to_primary, max_docs)
    if mode == "expanded":
        return expanded.expanded_doc_keys(row, profiles, alias_to_primary, max_docs=max_docs)
    if mode == "existing_then_expanded":
        existing = existing_doc_keys(row, profiles, alias_to_primary, max_docs)
        expanded_keys = expanded.expanded_doc_keys(row, profiles, alias_to_primary, max_docs=max_docs)
        return base.unique_keep_order(existing + expanded_keys)[:max_docs]
    raise ValueError(f"unknown doc mode: {mode}")


def fact_sequence_for_intents(intents: set[str]) -> list[str]:
    sequence: list[str] = []
    for intent in ["budget", "date", "submission", "eligibility", "summary", "general"]:
        if intent in intents or (intent == "general" and not sequence):
            sequence.extend(FACT_SEQUENCE[intent])
    return base.unique_keep_order(sequence)


def fact_sequence_rank(chunk: dict[str, Any], intents: set[str]) -> int:
    fact_type = base.chunk_fact_type(chunk)
    sequence = fact_sequence_for_intents(intents)
    try:
        return sequence.index(fact_type)
    except ValueError:
        return 99


def score_chunk(
    chunk: dict[str, Any],
    question: str,
    intents: set[str],
    source_index: dict[str, dict[str, Any]],
    bm25: BM25Index,
    *,
    scoring: str,
) -> float:
    bm25_score = bm25.score(chunk, query_tokens(question, intents))
    rule_score = expanded.score_expanded_chunk(
        chunk,
        question,
        intents,
        source_index,
        variant="existing_core_rr_source_final",
    )
    fact_rank = fact_sequence_rank(chunk, intents)
    canonical_bonus = max(0.0, 35.0 - fact_rank * 4.0)
    source_boost = expanded.source_final_boost(chunk, intents, source_index)

    if scoring == "bm25":
        return bm25_score * 12.0 + source_boost
    if scoring == "hybrid":
        return bm25_score * 7.0 + rule_score
    if scoring == "strict_pack":
        return canonical_bonus * 4.0 + rule_score + bm25_score * 2.0
    if scoring == "canonical":
        return canonical_bonus * 6.0 + source_boost + bm25_score
    if scoring == "rule":
        return rule_score
    raise ValueError(f"unknown scoring: {scoring}")


def order_chunks(
    chunks: list[tuple[float, dict[str, Any]]],
    intents: set[str],
    scoring: str,
) -> list[tuple[float, dict[str, Any]]]:
    if scoring in {"strict_pack", "canonical"}:
        return sorted(
            chunks,
            key=lambda item: (
                fact_sequence_rank(item[1], intents),
                base.fact_order_key(item[1]),
                -item[0],
            ),
        )
    return sorted(chunks, key=lambda item: (item[0], str(item[1].get("chunk_id") or "")), reverse=True)


def quotas_for_docs(num_docs: int, strategy: str, top_slots: int = 5) -> list[int]:
    if num_docs <= 0:
        return []
    if strategy == "sequential":
        return [top_slots] + [0] * (num_docs - 1)
    if strategy == "round_robin":
        quotas = [0] * num_docs
        for idx in range(top_slots):
            quotas[idx % num_docs] += 1
        return quotas
    if strategy == "adaptive":
        if num_docs == 1:
            return [top_slots]
        if num_docs == 2:
            return [3, 2]
        if num_docs == 3:
            return [2, 2, 1]
        quotas = [1] * min(num_docs, top_slots)
        return quotas + [0] * (num_docs - len(quotas))
    if strategy == "adaptive_heavy_first":
        if num_docs == 1:
            return [top_slots]
        if num_docs == 2:
            return [4, 1]
        if num_docs == 3:
            return [3, 1, 1]
        quotas = [2, 1, 1, 1] + [0] * max(0, num_docs - 4)
        return quotas[:num_docs]
    raise ValueError(f"unknown quota strategy: {strategy}")


def arrange_doc_picks(
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]],
    *,
    strategy: str,
    total_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    selected: list[tuple[float, dict[str, Any]]] = []
    quotas = quotas_for_docs(len(per_doc_picks), strategy)
    used = [0] * len(per_doc_picks)

    for doc_idx, quota in enumerate(quotas):
        for _ in range(quota):
            if used[doc_idx] < len(per_doc_picks[doc_idx]):
                selected.append(per_doc_picks[doc_idx][used[doc_idx]])
                used[doc_idx] += 1
                if len(selected) >= total_k:
                    return selected

    if strategy == "sequential":
        for doc_idx, picks in enumerate(per_doc_picks):
            while used[doc_idx] < len(picks):
                selected.append(picks[used[doc_idx]])
                used[doc_idx] += 1
                if len(selected) >= total_k:
                    return selected
    else:
        max_len = max((len(picks) for picks in per_doc_picks), default=0)
        for offset in range(max_len):
            for doc_idx, picks in enumerate(per_doc_picks):
                if used[doc_idx] <= offset and offset < len(picks):
                    selected.append(picks[offset])
                    used[doc_idx] = offset + 1
                    if len(selected) >= total_k:
                        return selected
    return selected[:total_k]


def select_variant(
    row: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    bm25: BM25Index,
    *,
    doc_mode: str,
    scoring: str,
    quota_strategy: str,
    max_docs: int,
    max_per_doc: int,
    total_k: int,
) -> list[dict[str, Any]]:
    question = str(row.get("question") or row.get("eval_question") or "")
    intents = base.classify_question_terms(question)
    doc_keys = candidate_doc_keys(row, profiles, alias_to_primary, mode=doc_mode, max_docs=max_docs)
    per_doc_picks: list[list[tuple[float, dict[str, Any]]]] = []
    seen: set[str] = set()

    for doc_key in doc_keys:
        profile = profiles.get(doc_key)
        if not profile:
            continue
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in profile.get("chunks", []):
            if not base.is_fact_candidate(chunk):
                continue
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen:
                continue
            score = score_chunk(chunk, question, intents, source_index, bm25, scoring=scoring)
            if score <= 0:
                continue
            scored.append((score, chunk))
        ordered = order_chunks(scored, intents, scoring)[:max_per_doc]
        for _, chunk in ordered:
            seen.add(str(chunk.get("chunk_id") or ""))
        per_doc_picks.append(ordered)

    selected = arrange_doc_picks(per_doc_picks, strategy=quota_strategy, total_k=total_k)
    variant_name = f"{doc_mode}_{scoring}_{quota_strategy}_d{max_docs}_p{max_per_doc}_k{total_k}"
    return [
        expanded.context_from_chunk(chunk, rank, score, variant_name, source_index)
        for rank, (score, chunk) in enumerate(selected[:total_k], 1)
    ]


def make_rows(
    predictions: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    alias_to_primary: dict[str, str],
    source_index: dict[str, dict[str, Any]],
    bm25: BM25Index,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    variant_name = config["variant"]
    for row in predictions:
        selected = select_variant(
            row,
            profiles,
            alias_to_primary,
            source_index,
            bm25,
            doc_mode=config["doc_mode"],
            scoring=config["scoring"],
            quota_strategy=config["quota_strategy"],
            max_docs=config["max_docs"],
            max_per_doc=config["max_per_doc"],
            total_k=config["total_k"],
        )
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
                "selection_stage": variant_name,
            }
            for item in selected
        ]
        new_row["evidence_selection_variant"] = variant_name
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_configs(
    max_docs_values: list[int],
    total_k_values: list[int],
    doc_modes: list[str],
    scorings: list[str],
    quota_strategies: list[str],
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for doc_mode in doc_modes:
        for scoring in scorings:
            for quota_strategy in quota_strategies:
                for max_docs in max_docs_values:
                    if doc_mode == "existing" and max_docs > 5:
                        continue
                    for total_k in total_k_values:
                        max_per_doc = 8
                        variant = (
                            f"{doc_mode}_{scoring}_{quota_strategy}"
                            f"_d{max_docs}_p{max_per_doc}_k{total_k}"
                        )
                        configs.append(
                            {
                                "variant": variant,
                                "doc_mode": doc_mode,
                                "scoring": scoring,
                                "quota_strategy": quota_strategy,
                                "max_docs": max_docs,
                                "max_per_doc": max_per_doc,
                                "total_k": total_k,
                            }
                        )
    return configs


def sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(row.get("evidence_recall_at_5") or 0),
        float(row.get("evidence_hit_at_5") or 0),
        -float(row.get("doc_hit_but_evidence_missed") or 999),
        float(row.get("context_evidence_recall") or 0),
    )


def write_summary_md(path: Path, rows: list[dict[str, Any]], output_dir: Path) -> None:
    lines = [
        "# Evidence Selection Sweep Experiment",
        "",
        "adaptive quota, document-internal BM25, strict fact pack, source_store final_* 보정을 조합해 evidence recall을 비교한 참고용 실험입니다.",
        "",
        f"- output_dir: `{output_dir}`",
        f"- variants: {len(rows)}",
        "",
        "## Top 20",
        "",
        "| rank | variant | evidence_recall@5 | evidence_hit@5 | context_evidence_recall | doc_recall@5 | doc_hit_but_evidence_missed |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for idx, row in enumerate(rows[:20], 1):
        lines.append(
            f"| {idx} | {row['variant']} | {float(row.get('evidence_recall_at_5', 0)):.4f} | "
            f"{float(row.get('evidence_hit_at_5', 0)):.4f} | "
            f"{float(row.get('context_evidence_recall', 0)):.4f} | "
            f"{float(row.get('doc_recall_at_5', 0)):.4f} | {row.get('doc_hit_but_evidence_missed', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `evidence_recall@5`가 높을수록 top-5 안에 gold evidence chunk를 더 많이 넣은 것입니다.",
            "- `evidence_hit@5`가 높을수록 문제별로 정답 근거가 하나라도 들어간 비율이 높습니다.",
            "- generation에 붙일 때는 recall만 보지 말고 hit, doc recall, context 길이도 같이 봐야 합니다.",
            "- 이 실험은 기존 eval 결과를 덮어쓰지 않고 별도 참고용 결과만 생성합니다.",
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
    parser.add_argument("--max-docs-values", default="3,5")
    parser.add_argument("--total-k-values", default="20,30")
    parser.add_argument("--doc-modes", default="existing")
    parser.add_argument("--scorings", default="strict_pack,hybrid,bm25,canonical,rule")
    parser.add_argument("--quota-strategies", default="adaptive,adaptive_heavy_first,round_robin,sequential")
    parser.add_argument("--save-top-n", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_k_values = [int(value.strip()) for value in args.top_k.split(",") if value.strip()]
    max_docs_values = [int(value.strip()) for value in args.max_docs_values.split(",") if value.strip()]
    total_k_values = [int(value.strip()) for value in args.total_k_values.split(",") if value.strip()]
    doc_modes = [value.strip() for value in args.doc_modes.split(",") if value.strip()]
    scorings = [value.strip() for value in args.scorings.split(",") if value.strip()]
    quota_strategies = [value.strip() for value in args.quota_strategies.split(",") if value.strip()]

    output_dir = args.output_dir / args.predictions.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    top_dir = output_dir / "top_variant_predictions"
    top_dir.mkdir(parents=True, exist_ok=True)

    predictions = base.read_jsonl(args.predictions)
    gold_rows = base.read_jsonl(args.gold)
    chunks = base.load_chunks(args.chunks)
    profiles, alias_to_primary = expanded.load_doc_profiles(chunks)
    source_index = expanded.load_source_store(args.source_store)
    bm25 = BM25Index(chunks)

    configs = build_configs(max_docs_values, total_k_values, doc_modes, scorings, quota_strategies)
    comparison_rows: list[dict[str, Any]] = []
    row_cache: dict[str, list[dict[str, Any]]] = {}
    diag_cache: dict[str, list[dict[str, Any]]] = {}

    baseline_summary, baseline_diag = score_rows(predictions, gold_rows, top_k_values)
    baseline_config = {
        "variant": "baseline_existing_context",
        "doc_mode": "baseline",
        "scoring": "baseline",
        "quota_strategy": "baseline",
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
        if idx % 25 == 0:
            print(f"scored {idx}/{len(configs)} variants")

    comparison_rows.sort(key=sort_key, reverse=True)
    write_csv(output_dir / "comparison.csv", comparison_rows)
    write_summary_md(output_dir / "summary.md", comparison_rows, output_dir)

    for row in comparison_rows[: args.save_top_n]:
        variant = row["variant"]
        variant_rows = row_cache[variant]
        diag_rows = diag_cache[variant]
        safe_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", variant)
        write_jsonl(top_dir / f"{safe_name}.jsonl", variant_rows)
        recall_diag.write_csv(top_dir / f"{safe_name}_evidence_recall_results.csv", diag_rows)

    print(json.dumps(comparison_rows[:20], ensure_ascii=False, indent=2))
    print(f"\nWrote sweep results to {output_dir}")


if __name__ == "__main__":
    main()
