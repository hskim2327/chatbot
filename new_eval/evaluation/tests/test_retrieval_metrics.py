import math

from rag_eval.retrieval_metrics import compute_retrieval_metrics


def test_phase1_metrics_use_unique_top5_and_nan_for_empty_ground_truth():
    scored = compute_retrieval_metrics(
        ground_truth_docs=["doc-c.hwp", "doc-d.hwp"],
        retrieved_docs=["doc-a.hwp", "doc-c.hwp", "doc-b.hwp", "doc-d.hwp", "doc-e.hwp"],
        top_k=5,
    )
    empty = compute_retrieval_metrics(
        ground_truth_docs=[],
        retrieved_docs=["doc-a.hwp"],
        top_k=5,
    )

    assert scored["hit_at_5"] == 1.0
    assert scored["mrr_at_5"] == 0.5
    assert round(scored["ndcg_at_5"], 6) == round(
        (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3)),
        6,
    )
    assert math.isnan(empty["hit_at_5"])
    assert math.isnan(empty["mrr_at_5"])
    assert math.isnan(empty["ndcg_at_5"])
