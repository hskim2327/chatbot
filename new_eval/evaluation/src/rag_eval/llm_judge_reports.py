"""Phase 4 LLM Judge 결과 파일 저장과 사람용 한글 표시 컬럼을 담당한다."""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from .config import PHASE4_EXPERIMENT_LOG
from .experiment_logger import append_experiment_log
from .llm_judge_schema import SUBSCORE_NAMES
from .path_utils import ensure_dir, ensure_parent, safe_json_value
from .reports import write_dataframe, write_json


RESULT_COLUMNS = [
    "id",
    "question",
    "judge_overall_score",
    "calculated_overall_score",
    "overall_label",
    "business_usefulness_score",
    "business_usefulness_rationale",
    "completeness_score",
    "completeness_rationale",
    "groundedness_score",
    "groundedness_rationale",
    "numeric_factuality_score",
    "numeric_factuality_rationale",
    "structure_clarity_score",
    "structure_clarity_rationale",
    "risk_control_score",
    "risk_control_rationale",
    "risk_level",
    "hallucination_risk",
    "main_strengths",
    "main_weaknesses",
    "unsupported_or_risky_claims",
    "needs_human_review",
    "judge_comment",
    "answer_latency_sec",
    "llm_judge_latency_sec",
    "latency_note",
    "case_evaluation_ko",
    "strengths_ko",
    "weaknesses_ko",
    "score_rationale_ko",
    "improvement_hint_ko",
    "risk_comment_ko",
    "score_cap_applied",
    "score_cap_reason",
    "score_disagreement_warning",
    "parse_error",
    "validation_error",
    "timeout_error",
    "structured_output_used",
    "fallback_json_mode_used",
    "retry_count",
    "error",
    "정답성 점수",
    "숫자/금액 정확성 점수",
    "근거성 점수",
    "완전성 점수",
    "종합 점수",
    "종합 판정",
    "답변 생성 시간초",
    "실패 사유 한글 요약",
    "주요 감점 항목",
    "실무 위험 설명",
    "점수 근거 한글 요약",
    "문항별 한글 총평",
    "개선 힌트",
]

KO_OVERALL_SCORE = "\uc885\ud569 \uc810\uc218"
KO_OVERALL_LABEL = "\uc885\ud569 \ud310\uc815"
KO_ANSWER_LATENCY = "\ub2f5\ubcc0 \uc0dd\uc131 \uc2dc\uac04\ucd08"
KO_FAILURE_REASON = "\uc2e4\ud328 \uc0ac\uc720 \ud55c\uae00 \uc694\uc57d"
KO_WEAK_ITEMS = "\uc8fc\uc694 \uac10\uc810 \ud56d\ubaa9"
KO_RISK_COMMENT = "\uc2e4\ubb34 \uc704\ud5d8 \uc124\uba85"
KO_RATIONALE = "\uc810\uc218 \uadfc\uac70 \ud55c\uae00 \uc694\uc57d"
KO_CASE_EVALUATION = "\ubb38\ud56d\ubcc4 \ud55c\uae00 \ucd1d\ud3c9"
KO_IMPROVEMENT = "\uac1c\uc120 \ud78c\ud2b8"
KO_SUMMARY_HEADING = "\uc804\uccb4 \ud3c9\uac00 \ucd1d\ud3c9"
KO_LATENCY_HEADING = "\ub808\uc774\ud134\uc2dc \ucc38\uace0 \uc9c0\ud45c"
KO_MAIN_STRENGTHS = "\uc8fc\uc694 \uac15\uc810"
KO_MAIN_WEAKNESSES = "\uc8fc\uc694 \uc57d\uc810"
KO_PRIORITIES = "\uac1c\uc120 \uc6b0\uc120\uc21c\uc704"

for _column in (
    KO_OVERALL_SCORE,
    KO_OVERALL_LABEL,
    KO_ANSWER_LATENCY,
    KO_FAILURE_REASON,
    KO_WEAK_ITEMS,
    KO_RISK_COMMENT,
    KO_RATIONALE,
    KO_CASE_EVALUATION,
    KO_IMPROVEMENT,
):
    if _column not in RESULT_COLUMNS:
        RESULT_COLUMNS.append(_column)

SUBSCORE_LABELS = {
    "business_usefulness": ("실무 유용성", "RFP 실무자가 답변을 실제 업무에 참고할 수 있는 정도"),
    "completeness": ("완전성", "질문과 근거 요약 기준으로 필요한 요소를 충분히 다뤘는지"),
    "groundedness": ("근거성", "답변이 검색 근거와 source_docs에 기반했는지"),
    "numeric_factuality": ("숫자/사실 정확성", "금액, 날짜, 기간, 자격, 제출서류 등 사실 정보가 위험하게 틀리지 않았는지"),
    "structure_clarity": ("구조 명확성", "문서별 요약, 비교축, 항목 구분 등 답변 구조가 읽기 쉬운지"),
    "risk_control": ("위험 통제", "문서에 없는 단정, 과장, 환각 위험을 억제했는지"),
}


def write_jsonl(rows: list[dict[str, Any]], path) -> None:
    """dict row 목록을 JSONL로 저장한다."""

    ensure_parent(path)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(safe_json_value(row), ensure_ascii=False) + "\n")


def _jsonish(value: Any) -> str:
    """list/dict 값을 CSV에서 읽기 쉬운 JSON 문자열로 바꾼다."""

    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _numeric(value: Any) -> float:
    """값을 float로 변환하고 실패하면 NaN을 반환한다."""

    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(converted) if not pd.isna(converted) else math.nan


def _score_100_from_5(value: Any) -> float:
    """1~5 점수를 100점 척도로 환산한다."""

    score = _numeric(value)
    return math.nan if math.isnan(score) else round(score / 5.0 * 100.0, 1)


def _overall_label_from_100(score_100: float) -> str:
    """100점 환산 점수에 대한 한글 판정 라벨을 반환한다."""

    if math.isnan(score_100):
        return "판정 불가"
    if score_100 >= 85:
        return "실무 사용 매우 적합"
    if score_100 >= 70:
        return "실무 사용 적합"
    if score_100 >= 55:
        return "제한적 참고 가능"
    if score_100 >= 40:
        return "실무 사용 부적합에 가까움"
    return "실무 사용 부적합"


def _boolish(value: Any) -> bool:
    """CSV/JSON 혼합 입력에서 boolean 의미를 보수적으로 판정한다."""

    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _failure_reason_ko(flat: dict[str, Any]) -> str:
    """Phase 4 row의 실패 또는 주의 사유를 한국어로 요약한다."""

    if flat.get("error"):
        return f"LLM Judge 처리 중 오류가 발생했습니다: {flat.get('error')}"
    if _boolish(flat.get("parse_error")):
        return "Judge 응답을 JSON으로 해석하지 못했습니다."
    if _boolish(flat.get("validation_error")):
        return "Judge 응답이 필수 schema 또는 점수 범위를 만족하지 못했습니다."
    if _boolish(flat.get("timeout_error")):
        return "Judge 호출 또는 처리 시간이 제한을 초과했습니다."
    reasons: list[str] = []
    if _numeric(flat.get("calculated_overall_score")) < 2.8:
        reasons.append("종합 점수가 낮아 실무 활용 전 검토가 필요합니다.")
    if str(flat.get("risk_level", "")).lower() == "high":
        reasons.append("risk_level이 high로 판단되었습니다.")
    if str(flat.get("hallucination_risk", "")).lower() == "high":
        reasons.append("환각 또는 근거 없는 단정 위험이 높습니다.")
    if _boolish(flat.get("score_cap_applied")):
        reasons.append("위험도 또는 핵심 항목 저점으로 총점 상한이 적용되었습니다.")
    if _boolish(flat.get("score_disagreement_warning")):
        reasons.append("LLM 총평 점수와 코드 계산 점수 차이가 큽니다.")
    return " ".join(reasons) if reasons else "큰 오류는 없지만 세부 점수와 근거를 함께 확인해야 합니다."


def _weak_items(flat: dict[str, Any]) -> str:
    """낮은 세부 점수를 한국어 감점 항목으로 요약한다."""

    items: list[str] = []
    score_map = {
        "business_usefulness_score": "실무 유용성",
        "completeness_score": "완전성",
        "groundedness_score": "근거성",
        "numeric_factuality_score": "숫자/사실 정확성",
        "structure_clarity_score": "구조 명확성",
        "risk_control_score": "위험 통제",
    }
    for column, label in score_map.items():
        score = _numeric(flat.get(column))
        if not math.isnan(score) and score <= 2:
            items.append(label)
    if flat.get("error"):
        items.append("처리 오류")
    if _boolish(flat.get("parse_error")):
        items.append("JSON parse 오류")
    if _boolish(flat.get("validation_error")):
        items.append("schema 검증 오류")
    return ", ".join(items) if items else "세부 점수 확인"


def _rationale_summary(flat: dict[str, Any]) -> str:
    """세부 rationale과 judge_comment를 짧은 한글 근거 요약으로 묶는다."""

    if flat.get("score_rationale_ko"):
        return str(flat.get("score_rationale_ko"))
    parts: list[str] = []
    if flat.get("judge_comment"):
        parts.append(str(flat.get("judge_comment")))
    for column in (
        "groundedness_rationale",
        "numeric_factuality_rationale",
        "completeness_rationale",
        "risk_control_rationale",
    ):
        value = str(flat.get(column, "")).strip()
        if value and value not in parts:
            parts.append(value)
    return " ".join(parts)[:500] if parts else "Judge 근거 설명이 비어 있습니다."


def _case_evaluation_ko(flat: dict[str, Any]) -> str:
    """문항별 한글 총평을 생성한다."""

    if flat.get("case_evaluation_ko"):
        return str(flat.get("case_evaluation_ko"))
    score = _numeric(flat.get("calculated_overall_score"))
    label = flat.get("종합 판정") or _overall_label_from_100(_score_100_from_5(score))
    weak_items = _weak_items(flat)
    risk = str(flat.get("risk_level", "") or "unknown")
    hallucination = str(flat.get("hallucination_risk", "") or "unknown")
    if math.isnan(score):
        return "Judge 점수를 계산하지 못했습니다. 오류와 validation 결과를 먼저 확인해야 합니다."
    return (
        f"이 문항의 종합 판정은 '{label}'입니다. 주요 확인 항목은 {weak_items}이며, "
        f"risk_level={risk}, hallucination_risk={hallucination}입니다. "
        "실무 활용 전 낮은 세부 점수와 근거 설명을 함께 검토하세요."
    )


def _improvement_hint(flat: dict[str, Any]) -> str:
    """Phase 4 실패 row에 대한 개선 힌트를 생성한다."""

    if flat.get("improvement_hint_ko"):
        return str(flat.get("improvement_hint_ko"))
    if flat.get("error") or _boolish(flat.get("parse_error")) or _boolish(flat.get("validation_error")):
        return "Judge 응답 형식, schema 검증 결과, API 오류 메시지를 먼저 확인하세요."
    if _numeric(flat.get("groundedness_score")) <= 2:
        return "답변이 검색 근거의 표현과 더 직접적으로 연결되도록 evidence 기반 문장을 보강하세요."
    if _numeric(flat.get("numeric_factuality_score")) <= 2:
        return "금액, 날짜, 기간, 자격요건, 제출서류 등 숫자/사실 정보를 근거와 대조해 수정하세요."
    if _numeric(flat.get("completeness_score")) <= 2:
        return "질문이 요구한 핵심 항목을 빠뜨리지 않도록 checklist 형태로 보강하세요."
    if str(flat.get("risk_level", "")).lower() == "high":
        return "문서에 없는 단정이나 과도한 추측 표현을 제거하고 확인 불가 표현을 사용하세요."
    return "세부 rationale과 원 답변을 비교해 낮은 항목부터 보완하세요."


def _add_human_columns(flat: dict[str, Any]) -> dict[str, Any]:
    """영어 내부 컬럼을 유지하면서 사람용 한글 표시 컬럼을 추가한다."""

    overall = _numeric(flat.get("calculated_overall_score"))
    overall_100 = _score_100_from_5(overall)
    flat["정답성 점수"] = flat.get("completeness_score", "")
    flat["숫자/금액 정확성 점수"] = flat.get("numeric_factuality_score", "")
    flat["근거성 점수"] = flat.get("groundedness_score", "")
    flat["완전성 점수"] = flat.get("completeness_score", "")
    flat[KO_OVERALL_SCORE] = "" if math.isnan(overall) else round(overall, 3)
    flat[KO_OVERALL_LABEL] = _overall_label_from_100(overall_100)
    flat[KO_ANSWER_LATENCY] = flat.get("answer_latency_sec", "")
    flat[KO_FAILURE_REASON] = _failure_reason_ko(flat)
    flat[KO_WEAK_ITEMS] = _weak_items(flat)
    flat[KO_RISK_COMMENT] = flat.get("risk_comment_ko") or (
        "문서에 없는 단정 또는 고위험 오류가 있는지 확인해야 합니다."
        if str(flat.get("risk_level", "")).lower() == "high"
        else "현재 결과 기준의 주요 실무 위험은 제한적입니다."
    )
    flat[KO_RATIONALE] = _rationale_summary(flat)
    flat[KO_CASE_EVALUATION] = _case_evaluation_ko(flat)
    flat["case_evaluation_ko"] = flat[KO_CASE_EVALUATION]
    flat[KO_IMPROVEMENT] = _improvement_hint(flat)
    return flat


def flatten_judge_result(row: dict[str, Any]) -> dict[str, Any]:
    """nested JudgeOutput을 CSV 저장용 flat row로 변환한다."""

    flat = {key: row.get(key, "") for key in RESULT_COLUMNS}
    subscores = row.get("subscores") if isinstance(row.get("subscores"), dict) else {}
    for name in SUBSCORE_NAMES:
        subscore = subscores.get(name, {}) if isinstance(subscores.get(name), dict) else {}
        flat[f"{name}_score"] = subscore.get("score", flat.get(f"{name}_score", ""))
        flat[f"{name}_rationale"] = subscore.get("rationale", flat.get(f"{name}_rationale", ""))
    for key in ("main_strengths", "main_weaknesses", "unsupported_or_risky_claims", "strengths_ko", "weaknesses_ko"):
        flat[key] = _jsonish(flat.get(key, ""))
    return _add_human_columns(flat)


def results_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Judge result row 목록을 표준 컬럼 DataFrame으로 만든다."""

    if not rows:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    return pd.DataFrame([flatten_judge_result(row) for row in rows]).reindex(columns=RESULT_COLUMNS)


def _distribution(series: pd.Series) -> dict[str, int]:
    """값 분포를 dict로 반환한다."""

    if series.empty:
        return {}
    return {str(key): int(value) for key, value in series.value_counts(dropna=False).to_dict().items()}


def _series_mean(results_df: pd.DataFrame, column: str) -> float:
    """DataFrame 컬럼 평균을 NaN-safe하게 계산한다."""

    if column not in results_df or results_df.empty:
        return float("nan")
    return float(pd.to_numeric(results_df[column], errors="coerce").mean())


def _latency_stats(results_df: pd.DataFrame) -> tuple[float, float, float]:
    """answer_latency_sec 평균/중앙값/최대값을 계산한다."""

    if "answer_latency_sec" not in results_df or results_df.empty:
        return float("nan"), float("nan"), float("nan")
    values = pd.to_numeric(results_df["answer_latency_sec"], errors="coerce").dropna()
    if values.empty:
        return float("nan"), float("nan"), float("nan")
    return float(values.mean()), float(values.median()), float(values.max())


def _official_overall(summary: dict[str, Any]) -> float:
    """summary에서 공식 종합 점수로 쓸 1~5 점수를 선택한다."""

    for key in ("average_calculated_overall_score", "average_judge_overall_score"):
        value = _numeric(summary.get(key))
        if not math.isnan(value):
            return value
    subscore_values = [
        _numeric(summary.get("average_business_usefulness_score")),
        _numeric(summary.get("average_completeness_score")),
        _numeric(summary.get("average_groundedness_score")),
        _numeric(summary.get("average_numeric_factuality_score")),
    ]
    valid = [value for value in subscore_values if not math.isnan(value)]
    return float(sum(valid) / len(valid)) if valid else float("nan")


def summarize_results(
    mode: str,
    reference_mode: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    total_inputs: int,
    results_df: pd.DataFrame,
    api_key_present: bool,
) -> dict[str, Any]:
    """Phase 4 결과 요약 dict를 만든다."""

    failed_count = int(results_df.get("error", pd.Series(dtype=str)).astype(str).ne("").sum()) if not results_df.empty else 0
    judged_count = int(len(results_df) - failed_count)
    latency_mean, latency_median, latency_max = _latency_stats(results_df)
    summary: dict[str, Any] = {
        "mode": mode,
        "reference_mode": reference_mode,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "total_inputs": int(total_inputs),
        "judged_count": judged_count,
        "failed_count": failed_count,
        "parse_error_count": int(results_df.get("parse_error", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0,
        "validation_error_count": int(results_df.get("validation_error", pd.Series(dtype=bool)).eq(True).sum())
        if not results_df.empty
        else 0,
        "timeout_count": int(results_df.get("timeout_error", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0,
        "api_key_present": bool(api_key_present),
        "mock_or_dry_run": mode in {"mock", "dry_run"},
        "average_answer_latency_sec": latency_mean,
        "median_answer_latency_sec": latency_median,
        "max_answer_latency_sec": latency_max,
    }
    summary["retry_count"] = (
        int(pd.to_numeric(results_df.get("retry_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
        if not results_df.empty
        else 0
    )
    summary["structured_output_used"] = (
        bool(results_df.get("structured_output_used", pd.Series(dtype=bool)).eq(True).any()) if not results_df.empty else False
    )
    summary["fallback_json_mode_used"] = (
        bool(results_df.get("fallback_json_mode_used", pd.Series(dtype=bool)).eq(True).any()) if not results_df.empty else False
    )
    score_columns = {
        "average_judge_overall_score": "judge_overall_score",
        "average_calculated_overall_score": "calculated_overall_score",
        "average_business_usefulness_score": "business_usefulness_score",
        "average_completeness_score": "completeness_score",
        "average_groundedness_score": "groundedness_score",
        "average_numeric_factuality_score": "numeric_factuality_score",
        "average_structure_clarity_score": "structure_clarity_score",
        "average_risk_control_score": "risk_control_score",
    }
    for output_key, column in score_columns.items():
        summary[output_key] = _series_mean(results_df, column)
    summary["risk_level_distribution"] = _distribution(results_df["risk_level"]) if "risk_level" in results_df else {}
    summary["hallucination_risk_distribution"] = (
        _distribution(results_df["hallucination_risk"]) if "hallucination_risk" in results_df else {}
    )
    summary["needs_human_review_count"] = (
        int(results_df.get("needs_human_review", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0
    )
    summary["score_cap_applied_count"] = (
        int(results_df.get("score_cap_applied", pd.Series(dtype=bool)).eq(True).sum()) if not results_df.empty else 0
    )
    summary["score_disagreement_warning_count"] = (
        int(results_df.get("score_disagreement_warning", pd.Series(dtype=bool)).eq(True).sum())
        if not results_df.empty
        else 0
    )
    official = _official_overall(summary)
    summary["official_overall_score"] = official
    summary["official_overall_score_100"] = _score_100_from_5(official)
    summary["official_overall_label_ko"] = _overall_label_from_100(summary["official_overall_score_100"])
    return summary


def _fmt(value: Any) -> str:
    """Markdown에 넣을 값 표시를 정리한다."""

    number = _numeric(value)
    if not math.isnan(number):
        return f"{number:.3f}"
    return "" if value is None else str(value)


def _fmt_100(value: Any) -> str:
    """100점 환산값 표시를 정리한다."""

    number = _numeric(value)
    return "" if math.isnan(number) else f"{number:.1f}"


def _subscore_summary_items(summary: dict[str, Any]) -> list[tuple[str, str, float]]:
    """summary의 세부 점수를 한글 라벨과 함께 모은다."""

    return [
        ("실무 유용성", "business_usefulness_score", _numeric(summary.get("average_business_usefulness_score"))),
        ("완전성", "completeness_score", _numeric(summary.get("average_completeness_score"))),
        ("근거성", "groundedness_score", _numeric(summary.get("average_groundedness_score"))),
        ("숫자/사실 정확성", "numeric_factuality_score", _numeric(summary.get("average_numeric_factuality_score"))),
        ("구조 명확성", "structure_clarity_score", _numeric(summary.get("average_structure_clarity_score"))),
        ("위험 통제", "risk_control_score", _numeric(summary.get("average_risk_control_score"))),
    ]


def _overall_review_text(summary: dict[str, Any]) -> dict[str, Any]:
    """실험 전체 총평에 필요한 강점/약점/개선 우선순위를 규칙 기반으로 만든다."""

    items = [item for item in _subscore_summary_items(summary) if not math.isnan(item[2])]
    strongest = max(items, key=lambda item: item[2]) if items else ("판정 불가", "", math.nan)
    weakest = min(items, key=lambda item: item[2]) if items else ("판정 불가", "", math.nan)
    score_100 = _numeric(summary.get("official_overall_score_100"))
    label = str(summary.get("official_overall_label_ko", "판정 불가"))
    failed_count = int(summary.get("failed_count", 0) or 0)
    needs_review = int(summary.get("needs_human_review_count", 0) or 0)
    cap_count = int(summary.get("score_cap_applied_count", 0) or 0)
    latency = _numeric(summary.get("average_answer_latency_sec"))

    strengths = [f"가장 강한 항목은 {strongest[0]}입니다."]
    weaknesses = [f"가장 약한 항목은 {weakest[0]}입니다."]
    priorities: list[str] = []
    failure_types: list[str] = []

    if weakest[1] == "groundedness_score":
        failure_types.append("근거 기반성이 낮은 답변")
        priorities.append("검색 근거와 답변 문장을 직접 연결하도록 생성 프롬프트를 보강")
    if weakest[1] == "numeric_factuality_score":
        failure_types.append("금액/날짜/자격/제출서류 등 사실 정보 오류")
        priorities.append("예산, 날짜, 자격요건, 제출서류 값을 원문 근거와 대조하는 후처리 강화")
    if weakest[1] == "completeness_score":
        failure_types.append("질문 요구사항 누락")
        priorities.append("답변 생성 시 질문의 핵심 항목을 checklist로 분해")
    if cap_count:
        failure_types.append("위험도 또는 핵심 항목 저점으로 인한 score cap")
        priorities.append("문서에 없는 단정과 고위험 표현을 줄이는 refusal/grounding 정책 강화")
    if needs_review:
        failure_types.append("사람 검토 필요 문항")
    if failed_count:
        failure_types.append("Judge 처리 실패 또는 오류 문항")
    if not failure_types:
        failure_types.append("뚜렷한 시스템 오류보다는 세부 품질 차이")
    if not priorities:
        priorities.append(f"{weakest[0]} 항목의 낮은 문항부터 원 답변과 evidence를 대조")
    if not math.isnan(latency) and latency >= 10:
        priorities.append("평균 답변 생성 시간이 길어 응답 속도 개선 여지도 확인")

    if math.isnan(score_100):
        total_comment = "이번 실험은 종합 점수를 계산할 수 없어 결과 파일의 오류와 validation 상태를 먼저 확인해야 합니다."
    else:
        total_comment = (
            f"이번 실험의 Phase 4 종합 점수는 {score_100:.1f}점으로, '{label}' 수준입니다. "
            f"{strongest[0]}은 상대적으로 양호하지만 {weakest[0]}이 가장 약하게 나타났습니다. "
            f"실무 사용 전에는 {', '.join(failure_types)}를 우선 확인하는 것이 좋습니다."
        )

    return {
        "total_comment": total_comment,
        "strongest": strongest,
        "weakest": weakest,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "failure_types": failure_types,
        "priorities": priorities,
    }


def write_llm_judge_summary(path, summary: dict[str, Any]) -> None:
    """Phase 4 LLM Judge 요약 Markdown을 저장한다."""

    ensure_parent(path)
    overall_review = _overall_review_text(summary)
    metric_rows = [
        ("실무 유용성", "business_usefulness_score", summary.get("average_business_usefulness_score"), SUBSCORE_LABELS["business_usefulness"][1]),
        ("완전성", "completeness_score", summary.get("average_completeness_score"), SUBSCORE_LABELS["completeness"][1]),
        ("근거성", "groundedness_score", summary.get("average_groundedness_score"), SUBSCORE_LABELS["groundedness"][1]),
        ("숫자/사실 정확성", "numeric_factuality_score", summary.get("average_numeric_factuality_score"), SUBSCORE_LABELS["numeric_factuality"][1]),
        ("구조 명확성", "structure_clarity_score", summary.get("average_structure_clarity_score"), SUBSCORE_LABELS["structure_clarity"][1]),
        ("위험 통제", "risk_control_score", summary.get("average_risk_control_score"), SUBSCORE_LABELS["risk_control"][1]),
        ("종합 점수", "calculated_overall_score", summary.get("official_overall_score"), "세부 점수 가중합과 cap rule을 반영한 공식 Phase 4 종합 점수"),
    ]
    lines = [
        "# Phase 4 LLM Judge 평가 요약",
        "",
        "이 결과는 Phase 1/2/3 공식 점수를 대체하지 않는 보조 종합 평가입니다.",
    ]
    if summary.get("mock_or_dry_run"):
        lines.append("mock 또는 dry_run 결과는 실제 품질 점수로 해석하지 마십시오.")
    lines.extend(
        [
            "API key 값은 저장하지 않고 존재 여부만 boolean으로 기록합니다.",
            "",
            "## 실행 정보",
            "",
            f"- mode: {summary.get('mode', '')}",
            f"- reference_mode: {summary.get('reference_mode', '')}",
            f"- model: {summary.get('model', '')}",
            f"- prompt_version: {summary.get('prompt_version', '')}",
            f"- schema_version: {summary.get('schema_version', '')}",
            f"- structured_output_used: {summary.get('structured_output_used', False)}",
            f"- fallback_json_mode_used: {summary.get('fallback_json_mode_used', False)}",
            f"- api_key_present: {summary.get('api_key_present', False)}",
            f"- 평가 입력 수: {summary.get('total_inputs', 0)}",
            f"- 평가 완료 수: {summary.get('judged_count', 0)}",
            f"- 실패 수: {summary.get('failed_count', 0)}",
            f"- retry_count: {summary.get('retry_count', 0)}",
            f"- parse_error_count: {summary.get('parse_error_count', 0)}",
            f"- validation_error_count: {summary.get('validation_error_count', 0)}",
            f"- timeout_count: {summary.get('timeout_count', 0)}",
            "",
            "## 종합 점수",
            "",
            f"- 원점수(1~5): {_fmt(summary.get('official_overall_score'))}",
            f"- 100점 환산: {_fmt_100(summary.get('official_overall_score_100'))}점",
            f"- 전체 판정: {summary.get('official_overall_label_ko', '')}",
            "",
            "## 전체 평가 총평",
            "",
            overall_review["total_comment"],
            "",
            f"## {KO_SUMMARY_HEADING}",
            "",
            overall_review["total_comment"],
            "",
            f"- 가장 강한 항목: {overall_review['strongest'][0]} ({_fmt(overall_review['strongest'][2])})",
            f"- 가장 약한 항목: {overall_review['weakest'][0]} ({_fmt(overall_review['weakest'][2])})",
            f"- 주요 실패 유형: {', '.join(overall_review['failure_types'])}",
            f"- 실무 사용 가능성: {summary.get('official_overall_label_ko', '')}",
            "",
            f"### {KO_MAIN_STRENGTHS}",
            "",
            *[f"- {item}" for item in overall_review["strengths"]],
            "",
            f"### {KO_MAIN_WEAKNESSES}",
            "",
            *[f"- {item}" for item in overall_review["weaknesses"]],
            "",
            f"### {KO_PRIORITIES}",
            "",
            *[f"- {item}" for item in overall_review["priorities"]],
            "",
            f"- 가장 강한 항목: {overall_review['strongest'][0]} ({_fmt(overall_review['strongest'][2])})",
            f"- 가장 약한 항목: {overall_review['weakest'][0]} ({_fmt(overall_review['weakest'][2])})",
            f"- 주요 실패 유형: {', '.join(overall_review['failure_types'])}",
            f"- 실무 사용 가능성: {summary.get('official_overall_label_ko', '')}",
            "",
            "### 주요 강점",
            "",
            *[f"- {item}" for item in overall_review["strengths"]],
            "",
            "### 주요 약점",
            "",
            *[f"- {item}" for item in overall_review["weaknesses"]],
            "",
            "### 개선 우선순위",
            "",
            *[f"- {item}" for item in overall_review["priorities"]],
            "",
            "## 항목별 평균 점수",
            "",
            "| 평가 항목 | 내부 컬럼 | 평균 점수(1~5) | 100점 환산 | 해석 |",
            "|---|---|---:|---:|---|",
        ]
    )
    for label, column, value, description in metric_rows:
        lines.append(f"| {label} | `{column}` | {_fmt(value)} | {_fmt_100(_score_100_from_5(value))} | {description} |")
    lines.extend(
        [
            "",
            "## 레이턴시 참고 지표",
            "",
            "레이턴시는 점수 계산에 반영하지 않는 참고값입니다. RAG 답변 생성 시간과 Judge API 처리 시간은 구분해서 해석해야 합니다.",
            "",
            f"- 평균 답변 생성 시간: {_fmt(summary.get('average_answer_latency_sec'))}초",
            f"- 중앙값 답변 생성 시간: {_fmt(summary.get('median_answer_latency_sec'))}초",
            f"- 최대 답변 생성 시간: {_fmt(summary.get('max_answer_latency_sec'))}초",
            "",
            "## 위험/검토 요약",
            "",
            f"- risk_level 분포: {summary.get('risk_level_distribution', {})}",
            f"- hallucination_risk 분포: {summary.get('hallucination_risk_distribution', {})}",
            f"- 사람 검토 필요 수: {summary.get('needs_human_review_count', 0)}",
            f"- score cap 적용 수: {summary.get('score_cap_applied_count', 0)}",
            f"- LLM 총평 점수와 계산 점수 불일치 경고 수: {summary.get('score_disagreement_warning_count', 0)}",
            "",
            "## 주요 해석",
            "",
            f"- 현재 종합 판정은 '{summary.get('official_overall_label_ko', '')}'입니다.",
            "- 낮은 세부 점수, high risk, parse/validation 오류가 있는 문항은 failure_cases.csv에서 먼저 확인하세요.",
            "- 사람이 보는 CSV에는 한글 표시 컬럼이 추가되어 있으며, 내부 계산 컬럼명은 영어로 유지됩니다.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_llm_judge_reports(
    output_dir,
    judge_inputs: list[dict[str, Any]],
    results_df: pd.DataFrame,
    summary: dict[str, Any],
    failure_df: pd.DataFrame,
    raw_results: list[dict[str, Any]] | None = None,
) -> None:
    """Phase 4 산출물을 저장한다."""

    ensure_dir(output_dir)
    write_jsonl(judge_inputs, output_dir / "phase4_llm_judge_inputs.jsonl")
    write_dataframe(results_df.reindex(columns=RESULT_COLUMNS), output_dir / "phase4_llm_judge_results.csv")
    write_json(raw_results if raw_results is not None else results_df.to_dict(orient="records"), output_dir / "phase4_llm_judge_results.json")
    write_dataframe(failure_df.reindex(columns=RESULT_COLUMNS), output_dir / "phase4_llm_judge_failure_cases.csv")
    write_llm_judge_summary(output_dir / "phase4_llm_judge_summary.md", summary)


def append_llm_judge_experiment_log(output_dir, experiment_meta: dict[str, Any], summary: dict[str, Any]) -> None:
    """Phase 4 experiment log를 append-only CSV로 기록한다."""

    log_dir = output_dir / "experiment_logs"
    append_experiment_log(
        log_dir / PHASE4_EXPERIMENT_LOG,
        {
            "experiment_id": experiment_meta["experiment_id"],
            "experiment_name": experiment_meta.get("experiment_name", ""),
            "run_datetime": experiment_meta["run_datetime"],
            "notes": experiment_meta.get("notes", ""),
            "mode": summary.get("mode", ""),
            "reference_mode": summary.get("reference_mode", ""),
            "provider": summary.get("provider", ""),
            "model": summary.get("model", ""),
            "prompt_version": summary.get("prompt_version", ""),
            "schema_version": summary.get("schema_version", ""),
            "judged_count": summary.get("judged_count", 0),
            "failed_count": summary.get("failed_count", 0),
            "parse_error_count": summary.get("parse_error_count", 0),
            "validation_error_count": summary.get("validation_error_count", 0),
            "timeout_count": summary.get("timeout_count", 0),
            "retry_count": summary.get("retry_count", 0),
            "api_key_present": summary.get("api_key_present", False),
            "structured_output_used": summary.get("structured_output_used", False),
            "fallback_json_mode_used": summary.get("fallback_json_mode_used", False),
            "average_judge_overall_score": summary.get("average_judge_overall_score", ""),
            "average_calculated_overall_score": summary.get("average_calculated_overall_score", ""),
            "average_business_usefulness_score": summary.get("average_business_usefulness_score", ""),
            "average_completeness_score": summary.get("average_completeness_score", ""),
            "average_groundedness_score": summary.get("average_groundedness_score", ""),
            "average_numeric_factuality_score": summary.get("average_numeric_factuality_score", ""),
            "average_structure_clarity_score": summary.get("average_structure_clarity_score", ""),
            "average_risk_control_score": summary.get("average_risk_control_score", ""),
            "average_answer_latency_sec": summary.get("average_answer_latency_sec", ""),
            "median_answer_latency_sec": summary.get("median_answer_latency_sec", ""),
            "max_answer_latency_sec": summary.get("max_answer_latency_sec", ""),
            "official_overall_score": summary.get("official_overall_score", ""),
            "official_overall_score_100": summary.get("official_overall_score_100", ""),
            "official_overall_label_ko": summary.get("official_overall_label_ko", ""),
            "risk_level_distribution": summary.get("risk_level_distribution", {}),
            "hallucination_risk_distribution": summary.get("hallucination_risk_distribution", {}),
            "needs_human_review_count": summary.get("needs_human_review_count", 0),
        },
    )
