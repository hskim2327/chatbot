from typing import Any

from app.rag.config import nfc


def infer_question_type(question: str) -> str:
    q = nfc(question)
    has_budget = any(k in q for k in ["예산", "사업비", "금액", "추정가격", "기초금액", "얼마"])
    has_purpose = any(k in q for k in ["목적", "배경", "효과", "필요성", "개선"])
    if has_budget and has_purpose:
        return "comparison"
    if has_budget:
        return "budget"
    if any(k in q for k in ["제출서류", "제안서", "구비서류"]):
        return "submission_documents"
    if any(k in q for k in ["참가자격", "입찰자격", "자격요건", "면허", "실적"]):
        return "eligibility"
    if any(k in q for k in ["마감", "기한", "입찰마감", "제출기한"]):
        return "deadline"
    if any(k in q for k in ["사업기간", "수행기간", "계약기간", "유지보수"]):
        return "duration"
    if has_purpose:
        return "purpose"
    if any(k in q for k in ["비교", "차이", "공통점", "둘 중"]):
        return "comparison"
    return "general"


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def metadata_priority(meta: dict[str, Any], question_type: str) -> int:
    fact_type = nfc(meta.get("fact_type"))
    answer_policy = nfc(meta.get("answer_policy"))
    score = 0
    if question_type == "budget":
        if fact_type in {"project_budget", "total_allocation"}:
            score += 80
        if _to_bool(meta.get("budget_answer_enabled")):
            score += 50
        if answer_policy == "allow_as_project_budget":
            score += 40
        if fact_type in {"threshold_budget", "estimated_price", "base_amount", "reference_amount", "payment_terms"}:
            score -= 50
    elif question_type == "purpose":
        if fact_type in {"project_purpose_effect", "project_background", "project_scope", "requirements", "document_summary"}:
            score += 60
    elif question_type == "eligibility" and fact_type in {"eligibility", "business_type"}:
        score += 60
    elif question_type == "deadline" and fact_type in {"bid_deadline", "deadline_term", "submission_logistics"}:
        score += 60
    elif question_type == "duration" and fact_type in {"project_duration", "maintenance_period", "warranty_period"}:
        score += 60
    elif question_type == "submission_documents" and fact_type in {"submission_documents", "submission_logistics", "table"}:
        score += 60
    elif question_type in {"general", "comparison"}:
        if fact_type in {"document_summary", "requirements", "project_scope", "project_purpose_effect", "project_budget", "document_identity", "table"}:
            score += 35
    return score


def rerank(question: str, rows: list[dict[str, Any]], question_type: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        meta = item.get("metadata") or {}
        base = item.get("rrf_score", item.get("similarity", item.get("sparse_score", 0))) or 0
        item["metadata_priority"] = metadata_priority(meta, question_type)
        item["final_score"] = float(base) + item["metadata_priority"] * 0.001
        out.append(item)
    return sorted(out, key=lambda x: x.get("final_score", 0), reverse=True)


def select_contexts(rows: list[dict[str, Any]], question_type: str, max_contexts: int) -> list[dict[str, Any]]:
    if question_type == "budget":
        safe = []
        for row in rows:
            meta = row.get("metadata") or {}
            if nfc(meta.get("fact_type")) in {"project_budget", "total_allocation"} and _to_bool(meta.get("budget_answer_enabled")):
                safe.append(row)
        if safe:
            return safe[:max_contexts]
    seen = set()
    selected = []
    for row in rows:
        cid = row.get("chunk_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        selected.append(row)
        if len(selected) >= max_contexts:
            break
    return selected
