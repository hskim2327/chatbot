"""Phase 4 LLM Judge 입력, 출력, 점수 후처리 schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RISK_LEVELS = {"low", "medium", "high"}
REFERENCE_MODES = {"evidence_only", "gold_guided"}
SUBSCORE_NAMES = (
    "business_usefulness",
    "completeness",
    "groundedness",
    "numeric_factuality",
    "structure_clarity",
    "risk_control",
)
POSTPROCESS_FIELDS = {
    "calculated_overall_score",
    "overall_label",
    "score_cap_applied",
    "score_cap_reason",
    "score_disagreement_warning",
    "parse_error",
    "validation_error",
    "error",
}
REQUIRED_OUTPUT_FIELDS = {
    "id",
    "judge_overall_score",
    "subscores",
    "risk_level",
    "hallucination_risk",
    "main_strengths",
    "main_weaknesses",
    "unsupported_or_risky_claims",
    "needs_human_review",
    "judge_comment",
}


def judge_output_json_schema() -> dict[str, Any]:
    """OpenAI Structured Outputs에 전달할 JudgeOutput JSON Schema를 만든다."""

    subscore_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "score": {"type": "integer", "minimum": 1, "maximum": 5},
            "label": {"type": "string"},
            "rationale": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        },
        "required": ["score", "label", "rationale", "evidence_refs"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "judge_overall_score": {"type": "integer", "minimum": 1, "maximum": 5},
            "subscores": {
                "type": "object",
                "additionalProperties": False,
                "properties": {name: subscore_schema for name in SUBSCORE_NAMES},
                "required": list(SUBSCORE_NAMES),
            },
            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "hallucination_risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "main_strengths": {"type": "array", "items": {"type": "string"}},
            "main_weaknesses": {"type": "array", "items": {"type": "string"}},
            "unsupported_or_risky_claims": {"type": "array", "items": {"type": "string"}},
            "needs_human_review": {"type": "boolean"},
            "judge_comment": {"type": "string"},
        },
        "required": sorted(REQUIRED_OUTPUT_FIELDS),
    }


@dataclass
class EvidenceSummary:
    """Judge prompt에 전달할 짧은 evidence summary."""

    source_file: str = ""
    chunk_id: str | None = None
    evidence_summary: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "EvidenceSummary":
        """문자열 또는 dict 값을 EvidenceSummary로 정규화한다."""

        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(
                source_file=str(value.get("source_file") or value.get("filename") or value.get("doc_id") or ""),
                chunk_id=None if value.get("chunk_id") is None else str(value.get("chunk_id")),
                evidence_summary=str(value.get("evidence_summary") or value.get("text") or ""),
            )
        return cls(evidence_summary=str(value))

    def to_dict(self) -> dict[str, Any]:
        """JSON으로 저장 가능한 dict로 변환한다."""

        return {
            "source_file": self.source_file,
            "chunk_id": self.chunk_id,
            "evidence_summary": self.evidence_summary,
        }


@dataclass
class JudgeInput:
    """LLM Judge에 전달할 입력 record."""

    id: str
    question: str
    rag_answer: str
    source_docs: list[str] = field(default_factory=list)
    retrieved_evidence_summaries: list[EvidenceSummary | dict[str, Any] | str] = field(default_factory=list)
    task_family: str = ""
    source_set: str = ""
    domain_gold_summary: str = ""
    ground_truth_answer_summary: str = ""
    warning_resolution_status: str = ""
    phase1_metrics: dict[str, Any] | None = None
    phase2_ragas_metrics: dict[str, Any] | None = None
    phase3_domain_metrics: dict[str, Any] | None = None

    def normalized_evidence(self) -> list[EvidenceSummary]:
        """evidence summary 목록을 EvidenceSummary 객체로 정규화한다."""

        return [EvidenceSummary.from_value(item) for item in self.retrieved_evidence_summaries]

    def to_prompt_dict(self, reference_mode: str = "evidence_only") -> dict[str, Any]:
        """reference mode에 맞춰 Judge prompt payload에 넣을 필드만 반환한다."""

        if reference_mode not in REFERENCE_MODES:
            raise ValueError(f"reference_mode must be one of {sorted(REFERENCE_MODES)}")

        payload: dict[str, Any] = {
            "id": self.id,
            "question": self.question,
            "rag_answer": self.rag_answer,
            "source_docs": self.source_docs,
            "retrieved_evidence_summaries": [item.to_dict() for item in self.normalized_evidence()],
        }
        if self.task_family:
            payload["task_family"] = self.task_family
        if self.source_set:
            payload["source_set"] = self.source_set
        if reference_mode == "gold_guided":
            payload["domain_gold_summary"] = self.domain_gold_summary
            payload["ground_truth_answer_summary"] = self.ground_truth_answer_summary
        return payload


def _require_fields(output: dict[str, Any]) -> None:
    """필수 출력 필드 존재 여부를 확인한다."""

    missing = sorted(REQUIRED_OUTPUT_FIELDS - set(output))
    if missing:
        raise ValueError(f"Judge output missing required fields: {missing}")


def _reject_unknown_fields(output: dict[str, Any]) -> None:
    """알 수 없는 최상위 필드는 validation error로 처리한다."""

    allowed = REQUIRED_OUTPUT_FIELDS | POSTPROCESS_FIELDS
    unknown = sorted(set(output) - allowed)
    if unknown:
        raise ValueError(f"Judge output has unknown fields: {unknown}")


def _validate_score(name: str, value: Any) -> None:
    """점수가 1~5 정수인지 확인한다."""

    if not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{name} must be an integer from 1 to 5")


def _validate_string_list(name: str, value: Any) -> None:
    """문자열 배열인지 확인한다."""

    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")


def _validate_subscores(subscores: Any, evidence_count: int | None) -> None:
    """nested subscore schema를 검증한다."""

    if not isinstance(subscores, dict):
        raise ValueError("subscores must be an object")
    missing = [name for name in SUBSCORE_NAMES if name not in subscores]
    if missing:
        raise ValueError(f"subscores missing required fields: {missing}")
    unknown = sorted(set(subscores) - set(SUBSCORE_NAMES))
    if unknown:
        raise ValueError(f"subscores has unknown fields: {unknown}")

    for name in SUBSCORE_NAMES:
        subscore = subscores[name]
        if not isinstance(subscore, dict):
            raise ValueError(f"subscores.{name} must be an object")
        for field_name in ("score", "label", "rationale", "evidence_refs"):
            if field_name not in subscore:
                raise ValueError(f"subscores.{name} missing {field_name}")
        _validate_score(f"subscores.{name}.score", subscore["score"])
        if not isinstance(subscore["label"], str):
            raise ValueError(f"subscores.{name}.label must be a string")
        if not isinstance(subscore["rationale"], str):
            raise ValueError(f"subscores.{name}.rationale must be a string")
        refs = subscore["evidence_refs"]
        if not isinstance(refs, list) or not all(isinstance(ref, int) for ref in refs):
            raise ValueError(f"subscores.{name}.evidence_refs must be a list of integers")
        if evidence_count is not None and any(ref < 0 or ref >= evidence_count for ref in refs):
            raise ValueError(f"subscores.{name}.evidence_refs contains out-of-range index")


def is_numeric_or_deadline_question(question: str) -> bool:
    """숫자/날짜/자격/제출/마감 관련 질문인지 휴리스틱으로 판단한다."""

    keywords = (
        "예산",
        "금액",
        "사업비",
        "원",
        "억원",
        "날짜",
        "기간",
        "마감",
        "기한",
        "자격",
        "제출",
        "서류",
        "일정",
        "deadline",
    )
    return any(keyword in question for keyword in keywords)


def overall_label(score: float) -> str:
    """calculated_overall_score 구간 라벨을 반환한다."""

    if score >= 4.5:
        return "실무 사용 매우 적합"
    if score >= 3.7:
        return "실무 사용 적합"
    if score >= 2.8:
        return "제한적 참고 가능"
    if score >= 1.8:
        return "실무 사용 부적합에 가까움"
    return "실무 사용 부적합"


def compute_overall_score(output: dict[str, Any], question: str = "") -> dict[str, Any]:
    """subscore 가중합과 cap rule로 공식 overall score를 계산한다."""

    subscores = output["subscores"]
    score = (
        0.20 * subscores["business_usefulness"]["score"]
        + 0.20 * subscores["completeness"]["score"]
        + 0.25 * subscores["groundedness"]["score"]
        + 0.20 * subscores["numeric_factuality"]["score"]
        + 0.10 * subscores["structure_clarity"]["score"]
        + 0.05 * subscores["risk_control"]["score"]
    )
    cap_reasons: list[str] = []
    cap_value: float | None = None

    def apply_cap(value: float, reason: str) -> None:
        nonlocal cap_value
        cap_value = value if cap_value is None else min(cap_value, value)
        cap_reasons.append(reason)

    if output["risk_level"] == "high":
        apply_cap(2.5, "risk_level=high")
    if output["hallucination_risk"] == "high":
        apply_cap(2.5, "hallucination_risk=high")
    if subscores["groundedness"]["score"] <= 2:
        apply_cap(3.0, "groundedness_score<=2")
    if subscores["numeric_factuality"]["score"] <= 2 and is_numeric_or_deadline_question(question):
        apply_cap(3.0, "numeric_factuality_score<=2_for_numeric_or_deadline_question")
    if subscores["risk_control"]["score"] <= 2:
        apply_cap(3.0, "risk_control_score<=2")

    if cap_value is not None:
        score = min(score, cap_value)
    rounded = round(float(score), 4)
    disagreement = abs(float(output["judge_overall_score"]) - rounded) >= 1.0
    if disagreement:
        output["needs_human_review"] = True

    return {
        "calculated_overall_score": rounded,
        "overall_label": overall_label(rounded),
        "score_cap_applied": cap_value is not None,
        "score_cap_reason": "; ".join(cap_reasons),
        "score_disagreement_warning": disagreement,
        "needs_human_review": output["needs_human_review"],
    }


def validate_judge_output(output: dict[str, Any], evidence_count: int | None = None, question: str = "") -> dict[str, Any]:
    """LLM Judge JSON 출력을 검증하고 후처리 필드를 추가한다."""

    _require_fields(output)
    _reject_unknown_fields(output)
    _validate_score("judge_overall_score", output["judge_overall_score"])
    _validate_subscores(output["subscores"], evidence_count)

    for field in ("risk_level", "hallucination_risk"):
        if output[field] not in RISK_LEVELS:
            raise ValueError(f"{field} must be one of {sorted(RISK_LEVELS)}")

    for field in ("main_strengths", "main_weaknesses", "unsupported_or_risky_claims"):
        _validate_string_list(field, output[field])

    if not isinstance(output["needs_human_review"], bool):
        raise ValueError("needs_human_review must be a boolean")
    if not isinstance(output["judge_comment"], str):
        raise ValueError("judge_comment must be a string")

    processed = dict(output)
    processed.update(compute_overall_score(processed, question=question))
    processed["parse_error"] = False
    processed["validation_error"] = False
    processed["error"] = ""
    return processed
