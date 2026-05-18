import json
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_TOP_K = (1, 3, 5, 10)


def load_eval_jsonl(path: str | Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            item = json.loads(line)
            if "query" not in item:
                raise ValueError(f"Missing query in eval row {line_no}: {item}")
            examples.append(item)

    return examples


def parse_top_k(value: str) -> tuple[int, ...]:
    top_k = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not top_k:
        raise ValueError("At least one top-k value is required.")
    return tuple(sorted(set(top_k)))


def evaluate_retriever(
    retriever: Any,
    examples: Sequence[dict[str, Any]],
    top_k_values: Iterable[int] = DEFAULT_TOP_K,
) -> dict[str, Any]:
    top_k_values = tuple(sorted(set(top_k_values)))
    if not examples:
        raise ValueError("No evaluation examples loaded.")
    if not top_k_values:
        raise ValueError("At least one top-k value is required.")

    max_k = max(top_k_values)
    totals = {
        k: {
            "recall": 0.0,
            "hit_rate": 0.0,
            "mrr": 0.0,
            "context_precision": 0.0,
        }
        for k in top_k_values
    }

    for example in examples:
        relevant_chunk_ids = _as_set(example.get("relevant_chunk_ids"))
        relevant_doc_ids = _as_set(example.get("relevant_doc_ids"))
        if not relevant_chunk_ids and not relevant_doc_ids:
            raise ValueError(
                "Each eval example must include relevant_chunk_ids or relevant_doc_ids. "
                f"Query: {example['query']}"
            )

        results = retriever.retrieve(example["query"], top_k=max_k)

        for k in top_k_values:
            top_results = results[:k]
            matches = [_is_relevant(item, relevant_chunk_ids, relevant_doc_ids) for item in top_results]
            matched_targets = _matched_targets(top_results, relevant_chunk_ids, relevant_doc_ids)
            target_count = len(relevant_chunk_ids or relevant_doc_ids)
            first_rank = _first_relevant_rank(matches)

            totals[k]["recall"] += len(matched_targets) / target_count
            totals[k]["hit_rate"] += 1.0 if any(matches) else 0.0
            totals[k]["mrr"] += (1.0 / first_rank) if first_rank else 0.0
            totals[k]["context_precision"] += (sum(matches) / len(top_results)) if top_results else 0.0

    num_examples = len(examples)
    metrics = {
        str(k): {name: value / num_examples for name, value in totals[k].items()}
        for k in top_k_values
    }

    return {
        "num_examples": num_examples,
        "top_k": metrics,
    }


def print_report(metrics: dict[str, Any], title: str | None = None) -> None:
    if title:
        print(title)
    print(f"examples: {metrics['num_examples']}")
    print("k	recall	hit_rate	mrr	context_precision")

    for k, values in metrics["top_k"].items():
        print(
            f"{k}	"
            f"{values['recall']:.4f}	"
            f"{values['hit_rate']:.4f}	"
            f"{values['mrr']:.4f}	"
            f"{values['context_precision']:.4f}"
        )


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _is_relevant(
    item: dict[str, Any],
    relevant_chunk_ids: set[str],
    relevant_doc_ids: set[str],
) -> bool:
    chunk_id = str(item.get("chunk_id"))
    doc_id = str(item.get("doc_id"))
    if relevant_chunk_ids:
        return chunk_id in relevant_chunk_ids
    return doc_id in relevant_doc_ids


def _matched_targets(
    items: Sequence[dict[str, Any]],
    relevant_chunk_ids: set[str],
    relevant_doc_ids: set[str],
) -> set[str]:
    if relevant_chunk_ids:
        return {
            str(item.get("chunk_id"))
            for item in items
            if str(item.get("chunk_id")) in relevant_chunk_ids
        }

    return {
        str(item.get("doc_id"))
        for item in items
        if str(item.get("doc_id")) in relevant_doc_ids
    }


def _first_relevant_rank(matches: Sequence[bool]) -> int | None:
    for idx, matched in enumerate(matches, 1):
        if matched:
            return idx
    return None
