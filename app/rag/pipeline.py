import time
import re
from typing import Any

from app.rag.config import MAX_CONTEXTS
from app.db.chroma_client import records_for_issuers
from app.rag.g2b import append_manual_lookup_answer, build_manual_lookup_contexts
from app.rag.llm import generate
from app.rag.rerank import infer_question_type, rerank, select_contexts
from app.rag.retrieval import hybrid_retrieve

SYSTEM_PROMPT = """
당신은 RFP 문서 질의응답 도우미입니다.
반드시 제공된 근거 안에서만 답하세요.
fact_type, answer_policy, budget_answer_enabled 같은 내부 메타데이터명은 답변에 노출하지 마세요.
예산 질문은 안전한 사업예산 근거가 있을 때만 금액을 말하고, 없으면 확인 불가라고 답하세요.
답변은 간결하게 작성하고 마지막에 출처를 포함하세요.
""".strip()


def _clean_issuers(issuers: list[str]) -> list[str]:
    out = []
    for issuer in issuers or []:
        issuer = issuer.strip()
        if issuer and issuer not in out:
            out.append(issuer)
    if not out:
        raise ValueError("issuer is required")
    return out


def _context_text(rows: list[dict[str, Any]], max_chars: int = 1800) -> str:
    blocks = []
    for i, row in enumerate(rows, 1):
        meta = row.get("metadata") or {}
        text = (row.get("text") or "")[:max_chars]
        blocks.append(
            f"""[근거 {i}]
문서: {meta.get('source_file', '')}
발주기관: {meta.get('issuer', '')}
사업명: {meta.get('project_name', '')}
섹션: {meta.get('section_path', meta.get('section_type', ''))}
유형: {meta.get('fact_type', '')}

본문:
{text}"""
        )
    return "\n\n".join(blocks)


def _fallback_answer(question: str, selected: list[dict[str, Any]], qtype: str) -> str:
    if not selected:
        return "현재 선택한 발주기관 문서군에서 답변에 필요한 근거를 찾지 못했습니다."

    sources = []
    snippets = []
    for row in selected[:3]:
        meta = row.get("metadata") or {}
        source = meta.get("source_file") or "검색 문서"
        if source not in sources:
            sources.append(source)
        text = re.sub(r"\s+", " ", row.get("text") or "").strip()
        if text:
            snippets.append(text[:260])

    if qtype == "budget":
        return f"현재 문서 근거만으로는 안전하게 확정 가능한 사업예산 금액을 찾지 못했습니다.\n\n출처: {sources[0]}"

    if qtype == "purpose":
        lead = "검색된 문서 근거 기준으로는 다음 내용이 질문과 가장 관련됩니다."
    else:
        lead = "LLM 답변 생성에는 실패했지만, 검색된 근거에서 확인되는 핵심 내용은 다음과 같습니다."

    body = "\n".join(f"- {snippet}" for snippet in snippets[:3]) or "- 관련 본문을 찾았지만 요약 가능한 텍스트가 비어 있습니다."
    return f"{lead}\n{body}\n\n출처: {', '.join(sources[:3])}"


def _budget_has_safe_context(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        meta = row.get("metadata") or {}
        fact_type = str(meta.get("fact_type", ""))
        budget_enabled = str(meta.get("budget_answer_enabled", "")).lower() in {"true", "1", "yes", "y"}
        if fact_type in {"project_budget", "total_allocation"} and budget_enabled:
            return True
    return False


def _to_context_response(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(rows, 1):
        meta = row.get("metadata") or {}
        out.append(
            {
                "rank": i,
                "chunk_id": row.get("chunk_id"),
                "retriever": row.get("retrievers") or row.get("retriever"),
                "score": row.get("final_score", row.get("rrf_score", row.get("similarity", 0))),
                "filename": meta.get("source_file"),
                "metadata": meta,
                "text": row.get("text", ""),
            }
        )
    return out


async def answer_question(question: str, issuers: list[str], max_contexts: int = MAX_CONTEXTS, include_debug: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    issuers = _clean_issuers(issuers)
    max_contexts = max(1, min(int(max_contexts or MAX_CONTEXTS), 8))
    qtype = infer_question_type(question)

    route = ["issuer_filter", "hybrid_dense_sparse"]
    retrieval = hybrid_retrieve(question, issuers)
    if retrieval.get("backfill"):
        route.append("ngram_backfill")
    ranked = rerank(question, retrieval["merged"], qtype)
    route.append("metadata_rerank")
    selected = select_contexts(ranked, qtype, max_contexts)
    route.append("budget_strict_selection" if qtype == "budget" else "context_selection")
    manual_lookup_contexts = []
    if qtype == "budget" and not _budget_has_safe_context(selected):
        manual_lookup_contexts = build_manual_lookup_contexts([*selected, *ranked])
        if not manual_lookup_contexts:
            manual_lookup_contexts = build_manual_lookup_contexts(records_for_issuers(issuers))
        if manual_lookup_contexts:
            route.append("g2b_manual_lookup")

    context = _context_text(selected)
    if context:
        user_prompt = f"질문:\n{question}\n\n근거:\n{context}"
        try:
            answer = await generate(SYSTEM_PROMPT, user_prompt, max_tokens=320)
        except Exception as exc:
            answer = _fallback_answer(question, selected, qtype)
            route.append("llm_fallback")
            llm_error = f"{type(exc).__name__}: {exc}"
        else:
            route.append("llm_answer")
            llm_error = None
    else:
        answer = _fallback_answer(question, selected, qtype)
        route.append("no_context")
        llm_error = None
    if manual_lookup_contexts:
        answer = append_manual_lookup_answer(answer, manual_lookup_contexts)

    debug = {}
    if include_debug:
        debug = {
            "dense_count": len(retrieval.get("dense", [])),
            "sparse_count": len(retrieval.get("sparse", [])),
            "backfill_count": len(retrieval.get("backfill", [])),
            "merged_count": len(retrieval.get("merged", [])),
            "selected_count": len(selected),
            "manual_lookup_count": len(manual_lookup_contexts),
            "notice_numbers": [ctx.get("notice_number") for ctx in manual_lookup_contexts],
            "llm_error": llm_error,
        }

    return {
        "answer": answer,
        "issuers": issuers,
        "question_type": qtype,
        "route": route,
        "retrieved_contexts": _to_context_response(selected),
        "manual_lookup_contexts": manual_lookup_contexts,
        "latency_sec": time.perf_counter() - started,
        "debug": debug,
    }
