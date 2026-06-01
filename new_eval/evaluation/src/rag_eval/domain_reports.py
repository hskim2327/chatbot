"""Phase 3 도메인 평가 결과 파일 저장과 사람용 한글 보강을 담당한다."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .path_utils import ensure_dir, ensure_parent, safe_json_value
from .reports import write_dataframe, write_json


PHASE3_LABELS: dict[str, tuple[str, str]] = {
    "phase3_task_score": ("Phase 3 대표 점수", "문항 유형별 대표 도메인 metric 점수"),
    "budget_numeric_accuracy": ("예산/금액 정확성", "정답 예산 금액과 합산 금액을 맞힌 정도"),
    "required_field_accuracy": ("필수 정보 정확성", "질문이 요구한 핵심 필드와 checklist를 포함한 정도"),
    "unanswerable_refusal_accuracy": ("답변불가 대응 정확성", "문서에 없는 질문에 확인 불가로 대응한 정도"),
    "multi_doc_structure_score": ("다중 문서 비교 구조 점수", "비교 대상 문서, 비교축, 출력 구조를 지킨 정도"),
    "robust_query_consistency_score": ("오타/구어체 견고성", "비표준 질문에서도 같은 문서와 핵심 필드를 유지한 정도"),
}

OPTIONAL_REPORT_METRICS: dict[str, tuple[str, str]] = {
    "hit_at_5": ("Top-5 정답 문서 포함률", "정답 문서가 top-5에 포함된 비율"),
    "mrr_at_5": ("첫 정답 문서 순위 점수", "정답 문서가 앞순위에 있을수록 높음"),
    "ndcg_at_5": ("정답 문서 순위 품질", "여러 정답 문서가 상위권에 배치될수록 높음"),
    "multi_doc_recall_at_5": ("다중 문서 회수율", "여러 정답 문서를 얼마나 회수했는지"),
    "answer_token_f1": ("답변 토큰 유사도", "기준 답변과 생성 답변의 내용 겹침 정도"),
    "budget_amount_exact_match": ("예산 금액 완전 일치율", "정답 예산 금액을 정확히 맞힌 비율"),
    "budget_amount_recall": ("예산 금액 재현율", "필요한 예산 금액을 빠짐없이 찾은 정도"),
    "budget_amount_precision": ("예산 금액 정밀도", "답변에 나온 금액 중 정답 금액 비율"),
}

TASK_LABELS = {
    "budget": "예산/금액",
    "required_fields": "필수 정보",
    "submission_eligibility_deadline": "제출서류/입찰자격/마감일",
    "unanswerable": "답변불가",
    "multi_doc_comparison": "다중 문서 비교",
    "robust_query_type_e": "오타/구어체 견고성",
}

TASK_MAIN_ITEMS = {
    "budget": "예산 금액, 합산 금액, 예산 유형",
    "required_fields": "발주기관, 사업명, 기간, 주요 요구사항",
    "submission_eligibility_deadline": "제출서류, 입찰자격, 마감일",
    "unanswerable": "확인 불가 표현, 금지 단정 회피",
    "multi_doc_comparison": "비교 대상 문서, 비교축, 출력 구조",
    "robust_query_type_e": "동일 문서 회수, 핵심 필드 유지",
}


def _fmt(value: Any) -> str:
    """Markdown 표에 넣을 숫자/문자 값을 짧게 포맷한다."""

    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return str(value)


def _as_float(value: Any) -> float:
    """값을 float로 변환하되 실패하면 NaN을 반환한다."""

    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(converted) if not pd.isna(converted) else math.nan


def _score_value(summary: dict[str, Any], column: str) -> Any:
    """summary dict에서 column 평균값을 찾는다."""

    if column == "phase3_task_score":
        return summary.get("phase3_task_score_mean")
    return summary.get(f"{column}_mean")


def _mean_if_present(results_df: pd.DataFrame, column: str) -> float:
    """results_df에 컬럼이 있을 때만 평균을 계산한다."""

    if column not in results_df:
        return math.nan
    values = pd.to_numeric(results_df[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else math.nan


def _latency_stats(results_df: pd.DataFrame) -> dict[str, float]:
    """answer_latency_sec 참고 통계를 계산한다."""

    if "answer_latency_sec" not in results_df:
        return {"mean": math.nan, "median": math.nan, "max": math.nan}
    values = pd.to_numeric(results_df["answer_latency_sec"], errors="coerce").dropna()
    if values.empty:
        return {"mean": math.nan, "median": math.nan, "max": math.nan}
    return {"mean": float(values.mean()), "median": float(values.median()), "max": float(values.max())}


def _score_verdict(score: Any, good: float = 0.85, fair: float = 0.7, weak: float = 0.5) -> str:
    """0~1 점수를 사람이 읽는 판정 문장으로 변환한다."""

    value = _as_float(score)
    if math.isnan(value):
        return "평가 결과가 없어 별도 확인이 필요합니다."
    if value >= good:
        return "우수합니다."
    if value >= fair:
        return "실사용 가능하지만 개선 여지가 있습니다."
    if value >= weak:
        return "부분적으로 동작하지만 안정성이 부족합니다."
    return "낮습니다. 실패 문항과 감점 항목을 우선 확인해야 합니다."


def _overall_interpretation(summary: dict[str, Any], failure_count: int) -> str:
    """Phase 3 summary에 넣을 전체 한글 해석 문장을 만든다."""

    mean_score = summary.get("phase3_task_score_mean")
    budget_score = summary.get("budget_numeric_accuracy_mean")
    parts: list[str] = []
    if not math.isnan(_as_float(mean_score)):
        parts.append(f"Phase 3 대표 점수는 {_fmt(mean_score)}로, {_score_verdict(mean_score)}")
    if not math.isnan(_as_float(budget_score)) and _as_float(budget_score) < 0.7:
        parts.append("특히 예산/금액 문항에서 필요한 금액을 놓치거나 잘못된 숫자를 포함했을 가능성이 있습니다.")
    if failure_count:
        parts.append(f"실패 또는 부분 감점 문항은 {failure_count}개입니다.")
    return " ".join(parts) if parts else "문항별 results.csv와 failure_cases.csv를 함께 확인해야 합니다."


def _retrieval_verdict(results_df: pd.DataFrame) -> str:
    """검색 성능 판정을 작성한다. Phase 3 단독 실행에서는 검색 지표가 없을 수 있다."""

    if "hit_at_5" not in results_df:
        return "Phase 3 리포트에는 검색 지표가 없으므로 Phase 1 eval_summary.md와 함께 해석해야 합니다."
    hit = _mean_if_present(results_df, "hit_at_5")
    return f"hit_at_5 평균은 {_fmt(hit)}이며, 검색 성능은 {_score_verdict(hit)}"


def _priority_text(summary: dict[str, Any]) -> str:
    """요약 점수에 따라 개선 우선순위를 제안한다."""

    priorities: list[str] = []
    if _as_float(summary.get("budget_numeric_accuracy_mean")) < 0.7:
        priorities.append("예산/금액 추출과 단위 검증")
    if _as_float(summary.get("required_field_accuracy_mean")) < 0.7:
        priorities.append("필수 필드/checklist 포함")
    if _as_float(summary.get("multi_doc_structure_score_mean")) < 0.7:
        priorities.append("다중 문서 비교 구조")
    if _as_float(summary.get("unanswerable_refusal_accuracy_mean")) < 0.7:
        priorities.append("문서 밖 정보에 대한 확인 불가 응답")
    if _as_float(summary.get("robust_query_consistency_score_mean")) < 0.7:
        priorities.append("오타/구어체 질문의 문서 및 핵심 필드 유지")
    if not priorities:
        priorities.append("실패 문항을 중심으로 세부 문항별 품질 점검")
    return " → ".join(priorities)


def _failure_reason_ko(row: pd.Series) -> str:
    """row metric 값을 기반으로 한글 실패 사유를 요약한다."""

    if str(row.get("error", "")):
        return f"평가 중 오류가 발생했습니다: {row.get('error')}"
    task = str(row.get("task_family", ""))
    low_reasons: list[str] = []
    score = _as_float(row.get("phase3_task_score"))
    if math.isnan(score):
        low_reasons.append("대표 점수를 계산하지 못했습니다.")
    elif score < 1.0:
        low_reasons.append("문항 유형의 핵심 정답 요소를 모두 만족하지 못했습니다.")
    if "hit_at_5" in row and _as_float(row.get("hit_at_5")) >= 1.0 and _as_float(row.get("answer_token_f1")) < 0.5:
        low_reasons.append("정답 문서는 찾았지만 답변이 기준 답변의 핵심 내용을 충분히 반영하지 못했습니다.")
    if task == "budget" and _as_float(row.get("budget_numeric_accuracy")) < 1:
        low_reasons.append("예산 금액이 기준값과 정확히 일치하지 않습니다.")
    if task in {"required_fields", "submission_eligibility_deadline"}:
        low_reasons.append("필수 필드 또는 checklist 항목 일부가 누락되었을 수 있습니다.")
    if task == "unanswerable":
        low_reasons.append("문서에 없는 정보에 대해 확인 불가로 답했는지 확인해야 합니다.")
    if task == "multi_doc_comparison":
        low_reasons.append("비교 대상 문서, 비교축, 출력 구조 중 일부가 부족할 수 있습니다.")
    if task == "robust_query_type_e":
        low_reasons.append("오타/구어체 질문에서도 같은 문서와 핵심 필드를 유지했는지 확인해야 합니다.")
    if str(row.get("warning", "")):
        low_reasons.append(f"metric warning: {row.get('warning')}")
    return " ".join(dict.fromkeys(low_reasons)) or "점수가 낮아 사람이 추가 확인해야 합니다."


def _weak_items(row: pd.Series) -> str:
    """주요 감점 항목을 한글로 나열한다."""

    task = str(row.get("task_family", ""))
    items = [TASK_MAIN_ITEMS.get(task, "대표 점수")]
    if str(row.get("error", "")):
        items.append("평가 오류")
    if str(row.get("warning", "")):
        items.append("warning")
    return ", ".join(dict.fromkeys(items))


def _improvement_hint(row: pd.Series) -> str:
    """실패 row에 대한 짧은 개선 힌트를 만든다."""

    task = str(row.get("task_family", ""))
    if task == "budget":
        return "사업금액과 제외해야 할 금액 후보를 구분하고, 답변 금액을 KRW 기준으로 검증하세요."
    if task == "required_fields":
        return "질문이 요구한 발주기관, 사업명, 기간, 주요 요구사항 키워드를 빠짐없이 포함하세요."
    if task == "submission_eligibility_deadline":
        return "제출서류, 입찰자격, 마감일 중 질문이 요구한 checklist 항목을 직접 답하세요."
    if task == "unanswerable":
        return "문서에 없는 정보는 단정하지 말고 확인 불가 표현을 사용하세요."
    if task == "multi_doc_comparison":
        return "비교 대상 문서를 모두 언급하고 공통점, 차이점, 문서별 구조를 분리하세요."
    if task == "robust_query_type_e":
        return "오타나 구어체가 있어도 같은 정답 문서와 핵심 필드를 유지하도록 검색과 답변 생성을 점검하세요."
    return "질문 의도와 정답 기준을 다시 확인하세요."


def _case_evaluation_ko(row: pd.Series) -> str:
    """문항별 사람이 읽는 한글 평가를 생성한다."""

    task_label = TASK_LABELS.get(str(row.get("task_family", "")), str(row.get("task_family", "")))
    score = _as_float(row.get("phase3_task_score"))
    if math.isnan(score):
        return f"{task_label} 문항의 대표 점수를 계산하지 못해 추가 확인이 필요합니다."
    if score >= 1.0:
        return f"{task_label} 문항의 핵심 평가 요소를 충족했습니다."
    return f"{task_label} 문항에서 {_failure_reason_ko(row)}"


def add_domain_human_columns(df: pd.DataFrame) -> pd.DataFrame:
    """영어 내부 컬럼을 유지하고 사람이 보는 한글 보조 컬럼을 추가한다."""

    enriched = df.copy()
    korean_columns = [
        "평가 유형 한글",
        "평가 유형",
        "주요 평가 항목",
        "문항별 한글 평가",
        "실패 사유 한글 요약",
        "주요 감점 항목",
        "개선 힌트",
    ]
    if enriched.empty:
        for column in korean_columns:
            enriched[column] = []
        return enriched

    task_series = enriched.get("task_family", pd.Series([""] * len(enriched), index=enriched.index)).astype(str)
    enriched["평가 유형 한글"] = task_series.map(TASK_LABELS).fillna(task_series)
    enriched["평가 유형"] = enriched["평가 유형 한글"]
    enriched["주요 평가 항목"] = task_series.map(TASK_MAIN_ITEMS).fillna("대표 점수")
    enriched["문항별 한글 평가"] = enriched.apply(_case_evaluation_ko, axis=1)
    enriched["실패 사유 한글 요약"] = enriched.apply(_failure_reason_ko, axis=1)
    enriched["주요 감점 항목"] = enriched.apply(_weak_items, axis=1)
    enriched["개선 힌트"] = enriched.apply(_improvement_hint, axis=1)
    return enriched


def _append_metric_rows(lines: list[str], rows: list[tuple[str, str, Any, str]]) -> None:
    """Markdown metric 표 row를 추가한다."""

    lines.extend(["", "| 평가 항목 | 내부 컬럼 | 평균 점수 | 해석 |", "|---|---|---:|---|"])
    for label, column, value, description in rows:
        lines.append(f"| {label} | `{column}` | {_fmt(value)} | {description} |")


def write_domain_summary_markdown(
    path,
    summary: dict[str, Any],
    warning_summary: dict[str, Any],
    results_df: pd.DataFrame | None = None,
    failure_count: int = 0,
) -> None:
    """Phase 3 도메인 평가 요약을 한글 Markdown으로 저장한다."""

    ensure_parent(path)
    results_df = pd.DataFrame() if results_df is None else results_df
    latency = _latency_stats(results_df)

    retrieval_rows = [
        (label, column, _mean_if_present(results_df, column), description)
        for column, (label, description) in OPTIONAL_REPORT_METRICS.items()
        if column in results_df
    ]
    answer_rows = [
        (label, column, _score_value(summary, column), description)
        for column, (label, description) in PHASE3_LABELS.items()
        if column != "budget_numeric_accuracy"
    ]
    budget_rows = [
        (
            PHASE3_LABELS["budget_numeric_accuracy"][0],
            "budget_numeric_accuracy",
            _score_value(summary, "budget_numeric_accuracy"),
            PHASE3_LABELS["budget_numeric_accuracy"][1],
        )
    ]

    lines = [
        "# Phase 3 RFP 도메인 평가 요약",
        "",
        "## 전체 요약",
        "",
        f"- 평가 문항 수: {summary.get('evaluated_count', 0)}",
        f"- 실패 문항 수: {failure_count}",
        f"- 제외 문항 수: {summary.get('skipped_count', 0)}",
        f"- accepted_warning 문항 수: {summary.get('accepted_warning_count', 0)}",
        "",
        "## 검색 성능 요약",
    ]
    if retrieval_rows:
        _append_metric_rows(lines, retrieval_rows)
    else:
        lines.extend(
            [
                "",
                "Phase 3 도메인 평가는 검색 metric을 새로 계산하지 않습니다. 검색 성능은 Phase 1의 `eval_summary.md`와 `eval_results.csv`를 함께 확인해야 합니다.",
            ]
        )

    lines.extend(["", "## 답변 내용 품질 요약"])
    _append_metric_rows(lines, answer_rows)

    lines.extend(["", "## 예산/금액 평가 요약"])
    _append_metric_rows(lines, budget_rows)

    lines.extend(
        [
            "",
            "## 레이턴시 참고값",
            "",
            "| 평가 항목 | 내부 컬럼 | 값 | 해석 |",
            "|---|---|---:|---|",
            f"| 평균 응답 시간 | `answer_latency_sec` | {_fmt(latency['mean'])} | RAG 답변 생성까지 걸린 평균 시간(초), 점수에는 반영하지 않음 |",
            f"| 중앙값 응답 시간 | `answer_latency_sec` | {_fmt(latency['median'])} | RAG 답변 생성 시간 중앙값(초) |",
            f"| 최대 응답 시간 | `answer_latency_sec` | {_fmt(latency['max'])} | 가장 오래 걸린 RAG 답변 생성 시간(초) |",
            "",
            "## 전체 한글 해석",
            "",
            _overall_interpretation(summary, failure_count),
            "",
            "## 종합 판정",
            "",
            f"- 검색 성능 판정: {_retrieval_verdict(results_df)}",
            f"- 답변 생성 품질 판정: {_score_verdict(summary.get('phase3_task_score_mean'))}",
            f"- 예산/금액 처리 판정: {_score_verdict(summary.get('budget_numeric_accuracy_mean'))}",
            f"- 전체 개선 우선순위: {_priority_text(summary)}",
            "",
            "## Warning 요약",
            "",
        ]
    )
    for key, value in warning_summary.items():
        lines.append(f"- {key}: {value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_domain_reports(
    output_dir,
    results_df: pd.DataFrame,
    summary: dict[str, Any],
    by_task: pd.DataFrame,
    failure_df: pd.DataFrame,
    warning_summary: dict[str, Any],
) -> None:
    """Phase 3 도메인 평가 산출물을 저장한다."""

    ensure_dir(output_dir)
    results_human_df = add_domain_human_columns(results_df)
    failure_human_df = add_domain_human_columns(failure_df)
    write_dataframe(results_human_df, output_dir / "phase3_domain_results.csv")
    write_json([safe_json_value(row) for row in results_human_df.to_dict(orient="records")], output_dir / "phase3_domain_results.json")
    write_dataframe(by_task, output_dir / "phase3_domain_by_task.csv")
    write_dataframe(failure_human_df, output_dir / "phase3_domain_failure_cases.csv")
    write_domain_summary_markdown(
        output_dir / "phase3_domain_summary.md",
        summary,
        warning_summary,
        results_df=results_human_df,
        failure_count=len(failure_human_df),
    )
