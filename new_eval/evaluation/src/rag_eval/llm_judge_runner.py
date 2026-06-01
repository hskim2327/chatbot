"""Phase 4 LLM Judge mock, dry_run, api placeholder 실행."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .domain_gold_loader import load_domain_gold
from .llm_judge_api import OpenAIJudgeAdapter
from .llm_judge_config import LLMJudgeSettings, load_llm_judge_settings
from .llm_judge_prompt import PROMPT_VERSION, SCHEMA_VERSION, build_judge_case_payload
from .llm_judge_reports import (
    append_llm_judge_experiment_log,
    results_dataframe,
    summarize_results,
    write_llm_judge_reports,
)
from .llm_judge_schema import EvidenceSummary, JudgeInput, SUBSCORE_NAMES, validate_judge_output


@dataclass
class LLMJudgeResult:
    """Phase 4 실행 결과 컨테이너."""

    inputs: list[dict[str, Any]]
    results: pd.DataFrame
    summary: dict[str, Any]
    failure_cases: pd.DataFrame


def _as_list(value: Any) -> list[Any]:
    """값을 list로 정규화한다."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and not value.strip():
        return []
    return [value]


def _prediction_latency_sec(row: dict[str, Any]) -> float | None:
    """prediction row의 latency_ms/latency_sec를 초 단위 참고값으로 변환한다."""

    if row.get("latency_sec") not in (None, ""):
        value = pd.to_numeric(pd.Series([row.get("latency_sec")]), errors="coerce").iloc[0]
        return float(value) if not pd.isna(value) else None
    if row.get("latency_ms") not in (None, ""):
        value = pd.to_numeric(pd.Series([row.get("latency_ms")]), errors="coerce").iloc[0]
        return float(value) / 1000.0 if not pd.isna(value) else None
    return None


def _prediction_latency_map(predictions_df: pd.DataFrame) -> dict[str, float]:
    """prediction id별 RAG 답변 생성 latency 참고값을 만든다."""

    latency_by_id: dict[str, float] = {}
    for row in predictions_df.to_dict(orient="records"):
        latency = _prediction_latency_sec(row)
        if latency is not None:
            latency_by_id[str(row.get("id"))] = latency
    return latency_by_id


def _attach_prediction_metadata(raw_results: list[dict[str, Any]], latency_by_id: dict[str, float]) -> None:
    """Judge raw result에 점수 미반영 prediction metadata를 붙인다."""

    for row in raw_results:
        latency = latency_by_id.get(str(row.get("id")))
        if latency is not None:
            row["answer_latency_sec"] = latency
            row["latency_note"] = "predictions latency_ms/latency_sec 기준 참고값이며 점수에는 반영하지 않음"


def _summarize_gold(gold: dict[str, Any]) -> str:
    """gold block을 500자 이내의 짧은 요약으로 변환한다."""

    task = gold.get("task_family", "")
    parts: list[str] = []
    if task == "budget":
        block = gold.get("budget_gold") or {}
        amounts = [str(item.get("amount_krw")) for item in _as_list(block.get("items")) if isinstance(item, dict)]
        if amounts:
            parts.append("budget_items=" + ", ".join(amounts))
        if block.get("total_krw") is not None:
            parts.append(f"total_krw={block.get('total_krw')}")
    elif task == "required_fields":
        fields = (gold.get("required_field_gold") or {}).get("fields", [])
        names = [str(field.get("field_name")) for field in fields if isinstance(field, dict)]
        if names:
            parts.append("required_fields=" + ", ".join(names))
    elif task == "submission_eligibility_deadline":
        block = gold.get("submission_eligibility_deadline_gold") or {}
        for key in ("submission_documents", "eligibility_terms", "deadline"):
            value = block.get(key)
            if value:
                parts.append(f"{key}={value}")
    elif task == "unanswerable":
        block = gold.get("unanswerable_gold") or {}
        parts.append(f"is_unanswerable={block.get('is_unanswerable')}")
        if block.get("forbidden_claim_types"):
            parts.append(f"forbidden_claim_types={block.get('forbidden_claim_types')}")
    elif task == "multi_doc_comparison":
        block = gold.get("multi_doc_comparison_gold") or {}
        parts.append(f"compared_docs={block.get('compared_docs', [])}")
        parts.append(f"comparison_axes={block.get('required_comparison_axes', [])}")
    elif task == "robust_query_type_e":
        block = gold.get("robust_query_gold") or {}
        parts.append(f"same_source_docs={block.get('expected_same_source_docs', [])}")
        parts.append(f"same_key_fields={block.get('expected_same_key_fields', [])}")
    return "; ".join(parts)[:500]


def _evidence_summaries(retrieved_contexts: Any) -> list[EvidenceSummary]:
    """retrieved_contexts에서 짧은 evidence summary를 만든다."""

    summaries: list[EvidenceSummary] = []
    for context in _as_list(retrieved_contexts):
        if not isinstance(context, dict):
            continue
        source_file = str(context.get("filename") or context.get("doc_id") or "")
        chunk_id = None if context.get("chunk_id") is None else str(context.get("chunk_id"))
        text = str(context.get("text") or "")
        summary = text[:300] if text else "retrieved_contexts 기준 근거 요약. 세부 text 없음"
        summaries.append(EvidenceSummary(source_file=source_file, chunk_id=chunk_id, evidence_summary=summary))
    return summaries[:5]


def build_judge_inputs(usable_gold: list[dict[str, Any]], predictions_df: pd.DataFrame, sample_size: int = 0) -> list[JudgeInput]:
    """gold와 prediction을 id 기준으로 묶어 JudgeInput 목록을 만든다."""

    records = usable_gold[:sample_size] if sample_size and sample_size > 0 else usable_gold
    prediction_map = {str(row.get("id")): row for row in predictions_df.to_dict(orient="records")}
    inputs: list[JudgeInput] = []
    for gold in records:
        prediction = prediction_map.get(str(gold.get("id")), {})
        if not prediction:
            continue
        inputs.append(
            JudgeInput(
                id=str(gold.get("id", "")),
                question=str(gold.get("question", "") or prediction.get("question", "")),
                rag_answer=str(prediction.get("answer", "") or ""),
                source_docs=[str(item) for item in _as_list(gold.get("source_docs"))],
                retrieved_evidence_summaries=_evidence_summaries(prediction.get("retrieved_contexts", [])),
                task_family=str(gold.get("task_family", "")),
                source_set=str(gold.get("source_set", "")),
                domain_gold_summary=_summarize_gold(gold),
                ground_truth_answer_summary=str(gold.get("notes", "") or ""),
                warning_resolution_status=str(gold.get("warning_resolution_status", "")),
            )
        )
    return inputs


def _subscore(score: int, label: str, rationale: str, evidence_refs: list[int] | None = None) -> dict[str, Any]:
    """mock output용 subscore dict를 만든다."""

    return {
        "score": score,
        "label": label,
        "rationale": rationale,
        "evidence_refs": evidence_refs or [],
    }


def _contains_numeric_question(question: str) -> bool:
    """숫자/날짜/자격/제출/마감 관련 질문인지 판단한다."""

    return any(keyword in question for keyword in ("예산", "금액", "원", "억원", "마감", "기한", "날짜", "자격", "제출", "서류"))


def _mock_judge_output(judge_input: JudgeInput) -> dict[str, Any]:
    """실제 LLM을 호출하지 않는 deterministic mock 결과를 만든다."""

    answer = judge_input.rag_answer.strip()
    evidence_count = len(judge_input.normalized_evidence())
    question = judge_input.question
    risky_patterns = ("낙찰되었다", "계약 체결", "확정", "선정되었습니다")
    risky_claim = any(pattern in answer for pattern in risky_patterns) and evidence_count == 0

    base = 3
    if not answer:
        base = 1
    elif answer and evidence_count > 0 and any(token for token in question.split() if token and token in answer):
        base = 4

    groundedness = 3 if evidence_count else 2
    hallucination_risk = "low" if evidence_count else "medium"
    risk_level = "low"
    risk_control = 4
    unsupported: list[str] = []
    if not answer:
        risk_level = "high"
        hallucination_risk = "high"
        risk_control = 1
        unsupported.append("답변이 비어 있음")
    elif risky_claim:
        risk_level = "high"
        hallucination_risk = "high"
        risk_control = 2
        groundedness = min(groundedness, 2)
        unsupported.append("근거 없는 위험 단정 표현")

    numeric_score = 3
    if _contains_numeric_question(question):
        numeric_score = 4 if any(char.isdigit() for char in answer) else 2

    output = {
        "id": judge_input.id,
        "judge_overall_score": max(1, min(5, base)),
        "subscores": {
            "business_usefulness": _subscore(base, "mock", "mock 기준 실무 유용성 점수", [0] if evidence_count else []),
            "completeness": _subscore(base, "mock", "question과 evidence summary 기준 mock 완전성 점수"),
            "groundedness": _subscore(groundedness, "mock", "evidence 존재 여부 기반 mock 근거성 점수", [0] if evidence_count else []),
            "numeric_factuality": _subscore(numeric_score, "mock", "숫자 관련 질문 휴리스틱 점수"),
            "structure_clarity": _subscore(3 if answer else 1, "mock", "mock 구조 명확성 점수"),
            "risk_control": _subscore(risk_control, "mock", "위험 단정 패턴 기반 mock 위험 통제 점수"),
        },
        "risk_level": risk_level,
        "hallucination_risk": hallucination_risk,
        "main_strengths": ["mock judge 흐름 검증용 결과"],
        "main_weaknesses": [] if answer else ["답변 없음"],
        "unsupported_or_risky_claims": unsupported,
        "needs_human_review": risk_level == "high",
        "judge_comment": "mock judge 결과이며 실제 품질 점수로 해석하지 않습니다.",
        "case_evaluation_ko": (
            "답변이 비어 있어 질문에 대한 평가가 어렵습니다."
            if not answer
            else (
                "검색 근거가 부족해 답변의 근거성을 확인하기 어렵습니다."
                if evidence_count == 0
                else "검색 근거와 답변이 일부 일치해 제한적으로 참고 가능한 mock 평가 결과입니다."
            )
        ),
        "strengths_ko": ["검색 근거와 답변 형식이 일부 확인됩니다."] if answer and evidence_count else [],
        "weaknesses_ko": (
            ["답변 없음"]
            if not answer
            else (["검색 근거 부족"] if evidence_count == 0 else ([] if numeric_score > 2 else ["숫자/금액 정보 확인 필요"]))
        ),
        "score_rationale_ko": "mock 규칙으로 답변 존재 여부, 근거 수, 위험 단정 표현, 숫자 포함 여부를 반영했습니다.",
        "improvement_hint_ko": (
            "최소한 근거 기반의 직접 답변을 생성해야 합니다."
            if not answer
            else (
                "검색 근거를 확보한 뒤 답변 문장과 연결해야 합니다."
                if evidence_count == 0
                else "금액 단위와 핵심 사실을 근거 문서와 다시 대조하세요."
            )
        ),
        "risk_comment_ko": (
            "근거 없는 단정 위험이 있습니다."
            if risk_level == "high" or evidence_count == 0
            else "현재 mock 기준의 실무 위험은 낮거나 제한적입니다."
        ),
    }
    return validate_judge_output(output, evidence_count=evidence_count, question=question)


def _failure_cases(results_df: pd.DataFrame) -> pd.DataFrame:
    """오류 또는 사람 검토 필요 row를 failure cases로 추린다."""

    if results_df.empty:
        return pd.DataFrame(columns=results_df.columns)
    mask = results_df.get("error", pd.Series([""] * len(results_df))).astype(str).ne("") | results_df.get(
        "needs_human_review", pd.Series([False] * len(results_df))
    ).eq(True)
    return results_df[mask].copy()


def run_llm_judge_evaluation(
    predictions_df: pd.DataFrame,
    domain_gold_path,
    output_dir,
    experiment_meta: dict[str, Any],
    mode: str = "mock",
    reference_mode: str = "evidence_only",
    model: str = "",
    sample_size: int = 0,
    settings: LLMJudgeSettings | None = None,
    api_client: Any | None = None,
) -> LLMJudgeResult:
    """Phase 4 mock/dry_run/api 평가를 실행한다."""

    if mode not in {"mock", "dry_run", "api"}:
        raise ValueError("llm judge mode must be one of mock, dry_run, api")
    if reference_mode not in {"evidence_only", "gold_guided"}:
        raise ValueError("llm judge reference_mode must be one of evidence_only, gold_guided")

    settings = settings or load_llm_judge_settings(model_override=model)
    if model:
        settings.model = model

    usable_gold, _ = load_domain_gold(domain_gold_path)
    judge_inputs = build_judge_inputs(usable_gold, predictions_df, sample_size=sample_size)
    input_dicts = [build_judge_case_payload(item, reference_mode=reference_mode) for item in judge_inputs]
    latency_by_id = _prediction_latency_map(predictions_df)

    raw_results: list[dict[str, Any]] = []
    if mode == "dry_run":
        results_df = pd.DataFrame()
    elif mode == "api":
        adapter = OpenAIJudgeAdapter(settings=settings, client=api_client)
        raw_results = [adapter.evaluate(item, reference_mode=reference_mode) for item in judge_inputs]
        _attach_prediction_metadata(raw_results, latency_by_id)
        results_df = results_dataframe(raw_results)
    else:
        raw_results = [_mock_judge_output(item) for item in judge_inputs]
        _attach_prediction_metadata(raw_results, latency_by_id)
        results_df = results_dataframe(raw_results)

    summary = summarize_results(
        mode=mode,
        reference_mode=reference_mode,
        provider=settings.provider,
        model=settings.model,
        prompt_version=settings.prompt_version or PROMPT_VERSION,
        schema_version=settings.schema_version or SCHEMA_VERSION,
        total_inputs=len(judge_inputs),
        results_df=results_df,
        api_key_present=settings.api_key_present,
    )
    failure_df = _failure_cases(results_df)
    write_llm_judge_reports(output_dir, input_dicts, results_df, summary, failure_df, raw_results=raw_results)
    append_llm_judge_experiment_log(output_dir, experiment_meta, summary)
    return LLMJudgeResult(inputs=input_dicts, results=results_df, summary=summary, failure_cases=failure_df)
