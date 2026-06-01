import os
import re
import unicodedata

from dotenv import load_dotenv

load_dotenv()

DENSE_K = int(os.getenv("DENSE_K", "50"))
SPARSE_K = int(os.getenv("SPARSE_K", "50"))
MAX_CONTEXTS = int(os.getenv("MAX_CONTEXTS", "5"))


def nfc(value: object) -> str:
    return unicodedata.normalize("NFC", "" if value is None else str(value))


def norm_text(value: object) -> str:
    text = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", nfc(value))
    return re.sub(r"\s+", " ", text).strip().lower()


QUESTION_FACT_TYPES = {
    "budget": {"project_budget", "total_allocation", "document_summary", "document_identity"},
    "purpose": {"project_purpose_effect", "project_background", "project_scope", "requirements", "document_summary"},
    "submission_documents": {"submission_documents", "submission_logistics", "table", "document_summary"},
    "eligibility": {"eligibility", "business_type", "threshold_budget", "document_summary"},
    "deadline": {"bid_deadline", "deadline_term", "submission_logistics", "document_summary"},
    "duration": {"project_duration", "maintenance_period", "warranty_period", "deadline_term", "document_summary"},
    "comparison": {"document_identity", "document_summary", "project_budget", "project_duration", "submission_documents", "eligibility", "project_purpose_effect", "project_scope"},
    "general": {"document_summary", "project_purpose_effect", "project_background", "project_scope", "requirements", "business_type", "project_budget", "project_duration", "eligibility", "document_identity", "table"},
}
