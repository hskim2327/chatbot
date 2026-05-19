import json

import pandas as pd

from rag_eval.loaders import load_predictions_jsonl


def test_predictions_jsonl_loader_requires_core_fields(tmp_path):
    predictions_path = tmp_path / "predictions.jsonl"
    predictions_path.write_text(
        json.dumps(
            {
                "id": "Q001",
                "question": "질문",
                "answer": "답변",
                "retrieved_contexts": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_predictions_jsonl(predictions_path)

    assert isinstance(loaded, pd.DataFrame)
    assert loaded.loc[0, "id"] == "Q001"
