"""평가 정책과 파일 경로 상수를 모아 둔 모듈."""

OFFICIAL_TOP_K = 5

PHASE1_METRIC_COLUMNS = ("hit_at_5", "mrr_at_5", "ndcg_at_5")
PHASE1_ANALYSIS_COLUMNS = ("doc_recall_at_5", "multi_doc_recall_at_5")

RAGAS_INPUT_SCHEMA = "question,answer,contexts,ground_truth"
RAGAS_COLUMN_MAP = ""
RAGAS_METRIC_NAMES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

EVAL_REQUIRED_COLUMNS = (
    "id",
    "type",
    "difficulty",
    "question",
    "ground_truth_answer",
    "ground_truth_docs",
    "metadata_filter",
    "history",
)

PREDICTION_REQUIRED_COLUMNS = (
    "id",
    "question",
    "answer",
    "retrieved_contexts",
)

CANONICAL_BATCH_START = 1
CANONICAL_BATCH_END = 25

DEFAULT_EVAL_DIR = "data/eval"
DEFAULT_OUTPUT_DIR = "eval/evaluation/outputs/eval"

PHASE1_EXPERIMENT_LOG = "phase1_retrieval_experiments.csv"
PHASE2_EXPERIMENT_LOG = "phase2_ragas_experiments.csv"
FAILURE_EXPERIMENT_LOG = "failure_analysis_experiments.csv"
