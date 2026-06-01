import csv

from rag_eval.experiment_logger import append_experiment_log


def test_append_experiment_log_adds_rows_without_overwriting(tmp_path):
    log_path = tmp_path / "phase2_ragas_experiments.csv"

    append_experiment_log(log_path, {"experiment_id": "exp1", "experiment_name": "base", "notes": "first"})
    append_experiment_log(log_path, {"experiment_id": "exp2", "experiment_name": "rerank", "notes": "second"})

    with log_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    assert [row["experiment_id"] for row in rows] == ["exp1", "exp2"]
    assert rows[0]["notes"] == "first"
    assert rows[1]["experiment_name"] == "rerank"
