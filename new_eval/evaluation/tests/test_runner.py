import json
import sys
import types

from rag_eval.ragas_evaluator import run_ragas_evaluation
from rag_eval.runner import main


def test_run_ragas_uses_default_evaluator_without_custom_llm_or_embeddings(monkeypatch):
    captured = {}

    class FakeDataset:
        @classmethod
        def from_dict(cls, data):
            captured["dataset"] = data
            return {"dataset": data}

    def fake_evaluate(dataset, metrics):
        captured["evaluate_args"] = {"dataset": dataset, "metrics": metrics}

        class Result:
            def to_pandas(self):
                import pandas as pd

                return pd.DataFrame(
                    [
                        {
                            "faithfulness": 1.0,
                            "answer_relevancy": 0.9,
                            "context_precision": 0.8,
                            "context_recall": 0.7,
                        }
                    ]
                )

        return Result()

    fake_ragas = types.ModuleType("ragas")
    fake_ragas.evaluate = fake_evaluate
    fake_ragas.__version__ = "0.1.21"
    fake_metrics = types.ModuleType("ragas.metrics")
    fake_metrics.faithfulness = "faithfulness"
    fake_metrics.answer_relevancy = "answer_relevancy"
    fake_metrics.context_precision = "context_precision"
    fake_metrics.context_recall = "context_recall"
    fake_datasets = types.ModuleType("datasets")
    fake_datasets.Dataset = FakeDataset

    monkeypatch.setitem(sys.modules, "ragas", fake_ragas)
    monkeypatch.setitem(sys.modules, "ragas.metrics", fake_metrics)
    monkeypatch.setitem(sys.modules, "datasets", fake_datasets)

    rows = [
        {
            "id": "Q001",
            "question": "질문",
            "answer": "답변",
            "ground_truth_answer": "정답",
            "retrieved_contexts": [{"text": "근거"}],
        }
    ]

    ragas_df, metadata = run_ragas_evaluation(rows)

    assert captured["dataset"] == {
        "question": ["질문"],
        "answer": ["답변"],
        "contexts": [["근거"]],
        "ground_truth": ["정답"],
    }
    assert set(captured["evaluate_args"].keys()) == {"dataset", "metrics"}
    assert metadata["ragas_default_evaluator_used"] is True
    assert metadata["ragas_input_schema"] == "question,answer,contexts,ground_truth"
    assert metadata["ragas_column_map"] == ""
    assert ragas_df.loc[0, "id"] == "Q001"
    assert ragas_df.loc[0, "ragas_error"] == ""


def test_require_ragas_returns_nonzero_after_saving_phase1_outputs(tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (eval_dir / "eval_batch_01.csv").write_text(
        "id,type,difficulty,question,ground_truth_answer,ground_truth_docs,metadata_filter,history\n"
        'Q001,A,하,질문,정답,"[""doc-a.hwp""]",{},[]\n',
        encoding="utf-8",
    )
    for idx in range(2, 26):
        (eval_dir / f"eval_batch_{idx:02d}.csv").write_text(
            "id,type,difficulty,question,ground_truth_answer,ground_truth_docs,metadata_filter,history\n",
            encoding="utf-8",
        )
    predictions_path = tmp_path / "predictions.jsonl"
    predictions_path.write_text(
        json.dumps(
            {
                "id": "Q001",
                "question": "질문",
                "answer": "답변",
                "retrieved_contexts": [{"rank": 1, "filename": "doc-a.hwp", "text": "근거"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs"

    exit_code = main(
        [
            "--eval-dir",
            str(eval_dir),
            "--predictions",
            str(predictions_path),
            "--output-dir",
            str(output_dir),
            "--canonical-only",
            "--enable-ragas",
            "--require-ragas",
        ]
    )

    assert exit_code != 0
    assert (output_dir / "eval_results.csv").exists()
    assert (output_dir / "experiment_logs" / "phase1_retrieval_experiments.csv").exists()
    assert (output_dir / "ragas_results.csv").exists()
