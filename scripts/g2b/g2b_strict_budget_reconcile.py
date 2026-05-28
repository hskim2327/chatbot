#!/usr/bin/env python3
"""Strictly reconcile project budget fields using local RFP text first, then validated G2B detail.

Policy:
- RFP original text is primary.
- Only clear project-budget labels are promoted to final_project_budget.
- Base amount / threshold / qualification / payment / evaluation amounts are not promoted.
- G2B detail is used only if RFP project budget is missing and the G2B notice is strongly matched.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None
try:
    import olefile
except Exception:  # pragma: no cover
    olefile = None

STRONG_PROJECT_BUDGET_LABELS = [
    "사업예산", "사업 예산", "사업금액", "사업 금액", "소요예산", "소요 예산",
    "총사업비", "총 사업비", "예산액", "배정예산", "배정 예산", "용역예산", "용역 예산",
]
BASE_AMOUNT_LABELS = ["기초금액", "기초 금액", "기초예산", "기초 예산"]
ESTIMATED_PRICE_LABELS = ["추정가격", "추정 가격", "예정가격", "예정 가격"]
OTHER_AMOUNT_LABELS = ["부가가치세", "VAT", "vat", "기타금액", "기타 금액"]

# Conservative: if these appear around a candidate, do not promote it to project budget.
NON_PROJECT_BUDGET_PATTERNS = [
    r"SW\s*사업정보.{0,120}(제출|저장소|적용대상)",
    r"사업정보\s*제출\s*적용대상",
    r"발주금액\s*기준.{0,60}(이상|이하|미만|초과)",
    r"사업금액.{0,30}(이상|이하|미만|초과)\s*사업",
    r"사업\s*금액.{0,30}(이상|이하|미만|초과)\s*사업",
    r"사업예산.{0,50}(이상|이하|미만|초과)",
    r"사업\s*예산.{0,50}(이상|이하|미만|초과)",
    r"총\s*사업\s*예산.{0,50}(이상|이하|미만|초과)",
    r"총\s*사업\s*금액.{0,50}(이상|이하|미만|초과)",
    r"총\s*사업비.{0,50}(이상|이하|미만|초과)",
    r"제안서\s*보상",
    r"사업금액.{0,40}하한",
    r"사업\s*금액.{0,40}하한",
    r"참여할\s*수\s*있는\s*사업금액의\s*하한",
    r"입찰참여\s*제한금액",
    r"대기업.{0,120}참여",
    r"중견기업.{0,120}참여",
    r"상호출자제한기업집단.{0,120}참여",
    r"소프트웨어사업자.{0,120}참여",
    r"총사업금액.{0,40}미만",
    r"사업금액의\s*100분의\s*50",
    r"하도급.{0,80}사업금액",
    r"입찰가격평가",
    r"최저입찰가격",
    r"해당입찰가격",
    r"추정가격의\s*100분의",
    r"평점\s*=",
    r"유사사업.{0,80}(실적|수행금액|금액)",
    r"수행실적.{0,80}금액",
    r"실적증명",
    r"계약금액.{0,80}(공동수급체|전자계약서|하도급|재하도급)",
    r"입찰보증금",
    r"보증금의\s*납부",
    r"가격제안서",
]

MATCH_STOPWORDS = [
    "긴급", "재공고", "입찰공고", "제안요청서", "용역", "사업", "구축", "시스템", "정보", "정보화전략계획",
    "isp", "ismp", "bpr", "컨설팅", "고도화", "수립", "개발", "운영", "관리", "통합", "차세대", "기능개선",
]

AMOUNT_RE = re.compile(r"(금\s*)?([0-9][0-9,\.\s]*)(\s*(?:억원|억\s*원|억|천원|천\s*원|백만원|백만\s*원|만원|만\s*원|원))?")

@dataclass
class AmountCandidate:
    value: str = ""
    value_krw: int | None = None
    label: str = ""
    role: str = ""
    confidence: str = ""
    source: str = ""
    snippet: str = ""
    start: int = 0
    score: float = 0.0
    comment: str = ""
    original_amount_text: str = ""


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def compact_norm(value: Any, remove_stopwords: bool = False) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"\[[^\]]+\]|\([^)]*\)|「|」|\[|\]|\(|\)", " ", text)
    if remove_stopwords:
        for word in MATCH_STOPWORDS:
            text = re.sub(re.escape(word), " ", text, flags=re.I)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def to_int_amount(value: Any) -> int | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else None


def format_krw(value: int | None) -> str:
    return f"{value:,}원" if value is not None else ""


def infer_amount_unit(label_window: str, captured_unit: str | None) -> tuple[str, str]:
    """Return (unit, confidence_reason). Empty unit means the amount format is too weak."""
    unit = normalize_text(captured_unit or "").replace(" ", "")
    if unit:
        return unit, "explicit_unit"
    context = normalize_text(label_window)
    # Common table/header forms: 사업예산(천원), (단위: 천원) ... 사업예산 386,893
    if re.search(r"(단위|사업예산|사업금액|소요예산|예산액|배정예산).{0,20}천\s*원", context):
        return "천원", "context_unit_thousand_won"
    if re.search(r"(단위|사업예산|사업금액|소요예산|예산액|배정예산).{0,20}백만\s*원", context):
        return "백만원", "context_unit_million_won"
    if re.search(r"(단위|사업예산|사업금액|소요예산|예산액|배정예산).{0,20}(억\s*원|억원)", context):
        return "억원", "context_unit_hundred_million_won"
    return "", "no_unit"


def parse_amount_to_krw(number_text: str, unit_text: str | None, label_window: str = "") -> tuple[int | None, str]:
    raw_with_commas = str(number_text or "")
    explicit_unit_from_number = ""
    if unit_text is None:
        m_unit = re.search(r"천\s*억\s*원|천억원|억원|억\s*원|억|천\s*원|천원|백만\s*원|백만원|만\s*원|만원|원", raw_with_commas)
        if m_unit:
            explicit_unit_from_number = normalize_text(m_unit.group(0)).replace(" ", "")
    raw = re.sub(r"[^0-9.]", "", raw_with_commas)
    if not raw:
        return None, "empty_number"
    try:
        num = float(raw) if "." in raw else int(raw)
    except ValueError:
        return None, "invalid_number"
    unit, reason = infer_amount_unit(label_window, unit_text or explicit_unit_from_number)
    raw_int = int(float(raw))
    # Context units such as "(단위: 천원)" are reliable only for table-sized values.
    # If the number is already a large comma-form won amount, do not multiply it again.
    if reason.startswith("context_unit") and raw_int >= 1_000_000 and "," in raw_with_commas:
        unit = "원"
        reason = "large_comma_won_over_context_unit"
    if not unit:
        # Accept large comma-form won values only. Reject TOC/page numbers and formula constants.
        if "," in raw_with_commas and raw_int >= 1_000_000:
            unit = "원"
            reason = "large_comma_won_without_unit"
        else:
            return None, reason
    if "천억" in unit:
        value = int(round(num * 1000 * 100_000_000))
    elif "억" in unit:
        value = int(round(num * 100_000_000))
    elif "백만원" in unit or "백만원" == unit:
        value = int(round(num * 1_000_000))
    elif "천원" in unit:
        value = int(round(num * 1_000))
    elif "만원" in unit:
        value = int(round(num * 10_000))
    else:
        value = int(round(num))
    return (value if value > 0 else None), reason


def snippet_at(text: str, start: int, end: int, radius: int = 170) -> str:
    return normalize_text(text[max(0, start - radius): min(len(text), end + radius)])[:900]


def is_non_project_budget_context(snippet: str) -> bool:
    text = normalize_text(snippet)
    return any(re.search(pattern, text, flags=re.I) for pattern in NON_PROJECT_BUDGET_PATTERNS)


def has_project_overview_context(snippet: str) -> bool:
    return any(token in snippet for token in [
        "사업개요", "사업 개요", "사업 일반", "사업일반", "일반사항", "추진개요", "사업명", "사 업 명",
        "사업기간", "계약방법", "입찰방식", "사업목적", "용역기간", "과업개요",
    ])


def extract_hwpx_full_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                name for name in zf.namelist()
                if name.endswith(".xml") and (name.startswith("Contents/") or name.startswith("BodyText/"))
            )
            parts: list[str] = []
            for name in names:
                raw = zf.read(name).decode("utf-8", errors="ignore")
                raw = re.sub(r"<[^>]+>", " ", raw)
                parts.append(html.unescape(raw))
            if parts:
                return normalize_text("\n".join(parts))
            if "Preview/PrvText.txt" in zf.namelist():
                return normalize_text(zf.read("Preview/PrvText.txt").decode("utf-8", errors="ignore"))
    except Exception:
        return ""
    return ""


def extract_hwp_text(path: Path) -> str:
    if olefile is None:
        return ""
    try:
        with olefile.OleFileIO(str(path)) as ole:
            streams = [s for s in ole.listdir() if len(s) >= 2 and s[0] == "BodyText" and s[1].startswith("Section")]
            parts: list[str] = []
            for stream in sorted(streams, key=lambda x: x[1]):
                data = ole.openstream(stream).read()
                try:
                    unpacked = zlib.decompress(data, -15)
                except zlib.error:
                    unpacked = data
                parts.append(unpacked.decode("utf-16le", errors="ignore"))
            return normalize_text("\n".join(parts))
    except Exception:
        return ""


def extract_pdf_text(path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
        return normalize_text("\n".join(page.extract_text() or "" for page in reader.pages))
    except Exception:
        return ""


def extract_source_text(project_root: Path, row: dict[str, str]) -> tuple[str, str]:
    rel_path = row.get("source_doc_path", "")
    path = project_root / rel_path if rel_path else Path("")
    fmt = row.get("source_doc_format", "").lower()
    if not path.exists():
        return "", "source_missing"
    if fmt == "hwpx" or path.suffix.lower() == ".hwpx":
        return extract_hwpx_full_text(path), "source_hwpx_full_xml"
    if fmt == "hwp" or path.suffix.lower() == ".hwp":
        return extract_hwp_text(path), "source_hwp_bodytext"
    if fmt == "pdf" or path.suffix.lower() == ".pdf":
        return extract_pdf_text(path), "source_pdf_text"
    return "", "source_unsupported"


def find_labeled_amounts(text: str, labels: list[str], role: str, source: str) -> list[AmountCandidate]:
    candidates: list[AmountCandidate] = []
    if not text:
        return candidates
    for label in labels:
        for lm in re.finditer(re.escape(label), text, flags=re.I):
            window = text[lm.end(): lm.end() + 180]
            am = AMOUNT_RE.search(window)
            if not am:
                continue
            start = lm.start()
            end = lm.end() + am.end()
            label_window = text[max(0, lm.start() - 120): lm.end() + am.end() + 60]
            value, amount_reason = parse_amount_to_krw(am.group(2), am.group(3), label_window)
            if value is None:
                continue
            snip = snippet_at(text, start, end)
            original_amount_text = normalize_text(am.group(0)).lstrip("금 ").strip()
            candidates.append(AmountCandidate(
                value=format_krw(value), value_krw=value, label=label, role=role,
                confidence=f"candidate:{amount_reason}", source=source, snippet=snip, start=start,
                original_amount_text=original_amount_text,
            ))
    return candidates


def score_project_candidate(candidate: AmountCandidate, text_len: int) -> AmountCandidate:
    score = 0.0
    label = candidate.label.replace(" ", "")
    if label in {"사업예산", "사업금액"}:
        score += 80
    elif label in {"소요예산", "배정예산", "예산액", "용역예산", "총사업비"}:
        score += 70
    else:
        score += 50
    if has_project_overview_context(candidate.snippet):
        score += 35
    # Prefer main-summary amounts that appear earlier, but do not let a later explicit project budget lose to a threshold.
    if text_len:
        score += max(0, 20 * (1 - candidate.start / max(text_len, 1)))
    if re.search(r"\b(이내|범위\s*내|VAT\s*포함|부가가치세\s*포함|부가세\s*포함|총액)\b", candidate.snippet):
        score += 5
    if candidate.value_krw is not None and candidate.value_krw < 1_000_000:
        score -= 200
        candidate.confidence = "rejected_small_amount"
        candidate.comment = "1원/0원/소액은 사업예산으로 승격하지 않음"
    if is_non_project_budget_context(candidate.snippet):
        score -= 200
        candidate.confidence = "rejected_non_project_budget_context"
        candidate.comment = "자격조건/실적/하한/입찰가격 산식 등 사업예산이 아닌 문맥"
    candidate.score = score
    return candidate


def select_rfp_budget(text: str, text_source: str) -> tuple[AmountCandidate | None, list[AmountCandidate], AmountCandidate | None, AmountCandidate | None]:
    project_candidates = [score_project_candidate(c, len(text)) for c in find_labeled_amounts(text, STRONG_PROJECT_BUDGET_LABELS, "project_budget", text_source)]
    accepted = [c for c in project_candidates if c.score >= 70 and c.confidence not in {"rejected_small_amount", "rejected_non_project_budget_context"}]
    accepted.sort(key=lambda c: (-c.score, c.start))
    selected = accepted[0] if accepted else None
    if selected:
        selected.confidence = "high"
        selected.comment = f"RFP 원문에서 '{selected.label}' 라벨로 명시된 사업예산/사업금액"
    base_candidates = find_labeled_amounts(text, BASE_AMOUNT_LABELS, "base_amount", text_source)
    base_candidates.sort(key=lambda c: c.start)
    base = base_candidates[0] if base_candidates else None
    if base:
        base.confidence = "separate_base_amount_only"
        base.comment = "RFP 원문 기초금액. 사업예산으로 확정하지 않고 별도 보관"
    estimated_candidates = find_labeled_amounts(text, ESTIMATED_PRICE_LABELS, "estimated_price", text_source)
    estimated_candidates.sort(key=lambda c: c.start)
    estimated = estimated_candidates[0] if estimated_candidates else None
    if estimated:
        estimated.confidence = "separate_estimated_price_only"
        estimated.comment = "RFP 원문 추정가격/예정가격. 사업예산으로 확정하지 않고 별도 보관"
    return selected, project_candidates, base, estimated


NON_PROJECT_AMOUNT_TEXT_RE = r"(?:금\s*)?(?P<amount>[0-9][0-9,\.\s]*(?:\s*(?:천\s*억원|천억원|천\s*억\s*원|억원|억\s*원|억|천원|천\s*원|백만원|백만\s*원|만원|만\s*원|원)))"
PERCENT_TEXT_RE = r"(?P<percent>100\s*분의\s*[0-9]+|[0-9]+\s*%)"

NON_PROJECT_AMOUNT_RULES = [
    {
        "fact_type": "reference_amount",
        "amount_type": "reference_amount",
        "amount_subtype": "sw_business_info_submission_threshold",
        "category_ko": "SW사업정보 제출 기준금액",
        "answer_policy": "route_only_not_final_answer",
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": False,
        "comment": "SW사업정보/사업정보 저장소 제출 적용대상 판단 기준금액. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:SW\s*사업정보|사업정보\s*제출|사업정보\s*저장소|발주금액\s*기준).{{0,180}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
            rf"{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과).{{0,120}}?(?:SW\s*사업정보|사업정보\s*제출|사업정보\s*저장소)",
        ],
    },
    {
        "fact_type": "threshold_budget",
        "amount_type": "threshold_budget",
        "amount_subtype": "software_business_participation_threshold",
        "category_ko": "소프트웨어 사업금액 하한/참여제한 기준",
        "answer_policy": "allow_for_eligibility_exclude_for_project_budget",
        "eligibility_answer_enabled": True,
        "payment_answer_enabled": False,
        "comment": "대기업/중견기업/상호출자제한기업집단 등 입찰참가 가능 여부 판단 기준금액. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:사업금액의\s*하한|참여할\s*수\s*있는\s*사업금액의\s*하한|입찰참여\s*제한금액).{{0,220}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
            rf"(?:대기업|중견기업|상호출자제한기업집단|중소\s*소프트웨어사업자).{{0,220}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
        ],
    },
    {
        "fact_type": "threshold_budget",
        "amount_type": "threshold_budget",
        "amount_subtype": "eligibility_sales_threshold",
        "category_ko": "입찰참가자격 매출 기준금액",
        "answer_policy": "allow_for_eligibility_exclude_for_project_budget",
        "eligibility_answer_enabled": True,
        "payment_answer_enabled": False,
        "comment": "입찰참가자격/자격요건 판단에 쓰이는 매출액 또는 자본금 기준. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:입찰참가자격|참가자격|자격요건|자격).{{0,240}}?(?:매출액|매출|자본금).{{0,120}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)",
            rf"(?:매출액|매출|자본금).{{0,120}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과).{{0,160}}?(?:입찰참가자격|참가자격|자격요건|자격)",
        ],
    },
    {
        "fact_type": "threshold_budget",
        "amount_type": "threshold_budget",
        "amount_subtype": "eligibility_performance_threshold",
        "category_ko": "입찰참가자격 수행실적 기준금액",
        "answer_policy": "allow_for_eligibility_exclude_for_project_budget",
        "eligibility_answer_enabled": True,
        "payment_answer_enabled": False,
        "comment": "입찰참가자격/평가에서 요구하는 유사사업 수행실적 또는 단일실적 기준금액. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:수행실적|유사사업|실적금액|단일실적).{{0,220}}?(?:수행금액|계약금액|실적|금액).{{0,100}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
            rf"(?:최근\s*[0-9]+\s*년|공고일\s*기준).{{0,180}}?(?:수행실적|유사사업|단일실적).{{0,140}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
        ],
    },
    {
        "fact_type": "reference_amount",
        "amount_type": "reference_amount",
        "amount_subtype": "proposal_compensation_threshold",
        "category_ko": "제안서 보상 기준금액",
        "answer_policy": "route_only_not_final_answer",
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": False,
        "comment": "제안서 보상 대상 여부 판단 기준금액. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:제안서\s*보상|보상대상사업|제안서\s*보상기준).{{0,220}}?(?:사업예산|총사업예산|총\s*사업예산|사업금액|총사업금액)?.{{0,80}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과)?",
            rf"(?:사업예산|총사업예산|총\s*사업예산|사업금액|총사업금액).{{0,100}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과).{{0,180}}?(?:제안서\s*보상|보상대상사업|제안서\s*보상기준)",
        ],
    },
    {
        "fact_type": "payment_terms",
        "amount_type": "payment_terms",
        "amount_subtype": "payment_schedule_amount_or_rate",
        "category_ko": "대금지급 조건 금액/비율",
        "answer_policy": "allow_for_payment_terms_exclude_for_project_budget",
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": True,
        "comment": "선금/중도금/잔금 등 지급조건에 쓰이는 금액 또는 비율. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:선금|중도금|잔금|지급조건|지급방법|지급률|지급비율|하도급\s*지급대금).{{0,120}}?{NON_PROJECT_AMOUNT_TEXT_RE}\s*(?P<comparison>이상|이하|미만|초과|이내)?",
        ],
    },
]

NON_PROJECT_PERCENT_RULES = [
    {
        "fact_type": "reference_amount",
        "amount_type": "reference_amount",
        "amount_subtype": "bid_price_evaluation_rate",
        "category_ko": "입찰가격평가 비율",
        "answer_policy": "route_only_not_final_answer",
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": False,
        "comment": "입찰가격평가 산식에 쓰이는 비율. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:입찰가격평가|가격평가|입찰가격|평점|추정가격).{{0,240}}?{PERCENT_TEXT_RE}",
            rf"{PERCENT_TEXT_RE}.{{0,160}}?(?:입찰가격평가|가격평가|입찰가격|추정가격)",
        ],
    },
    {
        "fact_type": "payment_terms",
        "amount_type": "payment_terms",
        "amount_subtype": "payment_schedule_rate",
        "category_ko": "대금지급 조건 비율",
        "answer_policy": "allow_for_payment_terms_exclude_for_project_budget",
        "eligibility_answer_enabled": False,
        "payment_answer_enabled": True,
        "comment": "선금/중도금/잔금 등 지급조건에 쓰이는 비율. 사업예산 답변에는 사용 금지.",
        "patterns": [
            rf"(?:선금|중도금|잔금|대금지급|지급조건|지급방법).{{0,160}}?{PERCENT_TEXT_RE}",
        ],
    },
]


def original_amount_unit(original_amount_text: str, fallback_reason: str = "") -> str:
    text = normalize_text(original_amount_text).replace(" ", "")
    for unit in ["천억원", "천억", "억원", "억", "천원", "백만원", "만원", "원"]:
        if unit in text:
            return unit
    if "context_unit_thousand_won" in fallback_reason:
        return "천원"
    if "context_unit_million_won" in fallback_reason:
        return "백만원"
    if "context_unit_hundred_million_won" in fallback_reason:
        return "억원"
    return "원" if text else ""


def parse_percent_text(percent_text: str) -> tuple[float | None, str, str]:
    raw = normalize_text(percent_text)
    if not raw:
        return None, "", ""
    if "100" in raw and "분의" in raw:
        m = re.search(r"100\s*분의\s*([0-9]+)", raw)
        if m:
            return float(m.group(1)), raw, "percent"
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", raw)
    if m:
        return float(m.group(1)), raw, "percent"
    return None, raw, ""


def is_non_project_amount_noise(rule: dict[str, Any], amount_text: str, value_krw: int, comparison: str, evidence: str) -> bool:
    subtype = str(rule.get("amount_subtype", ""))
    compact_amount = normalize_text(amount_text).replace(" ", "")
    compact_evidence = normalize_text(evidence)
    # 기초금액 1원 같은 원문 금액은 별도 base_amount 컬럼에 보존한다.
    # 여기서는 보조 fact 내부의 서식 번호/OCR 조각만 제거한다.
    if value_krw < 10_000 and re.search(r"(?:별지|서식|붙임|제안서\s*페이지|제안사\s*점수|배점|점수|원본|사본|각\s*1부|페이지)", compact_evidence):
        return True
    if re.fullmatch(r"0*[0-9]{1,3}(?:\.)?원", compact_amount) and not comparison:
        return True
    if subtype == "sw_business_info_submission_threshold" and not comparison:
        return True
    if subtype == "payment_schedule_amount_or_rate" and re.search(r"사업금액|사업예산|총사업비|용역비용|용역비", compact_evidence):
        return True
    return False


def make_non_project_amount_fact(rule: dict[str, Any], match: re.Match[str], text: str, text_source: str) -> dict[str, Any] | None:
    amount_text = normalize_text(match.groupdict().get("amount", ""))
    evidence = snippet_at(text, match.start(), match.end(), radius=190)
    value_krw, amount_reason = parse_amount_to_krw(amount_text, None, text[max(0, match.start() - 140): match.end() + 80])
    if value_krw is None:
        return None
    comparison = normalize_text(match.groupdict().get("comparison", ""))
    if is_non_project_amount_noise(rule, amount_text, value_krw, comparison, evidence):
        return None
    return {
        "fact_type": rule["fact_type"],
        "amount_type": rule["amount_type"],
        "amount_subtype": rule["amount_subtype"],
        "category_ko": rule["category_ko"],
        "value_kind": "krw",
        "amount_raw": amount_text,
        "amount_krw": value_krw,
        "amount_unit": original_amount_unit(amount_text, amount_reason),
        "comparison": comparison,
        "answer_policy": rule["answer_policy"],
        "budget_answer_enabled": False,
        "eligibility_answer_enabled": bool(rule["eligibility_answer_enabled"]),
        "payment_answer_enabled": bool(rule["payment_answer_enabled"]),
        "source_origin": text_source,
        "evidence_snippet": evidence,
        "comment": rule["comment"],
    }


def make_non_project_percent_fact(rule: dict[str, Any], match: re.Match[str], text: str, text_source: str) -> dict[str, Any] | None:
    value, raw, unit = parse_percent_text(match.groupdict().get("percent", ""))
    if value is None:
        return None
    return {
        "fact_type": rule["fact_type"],
        "amount_type": rule["amount_type"],
        "amount_subtype": rule["amount_subtype"],
        "category_ko": rule["category_ko"],
        "value_kind": "percent",
        "amount_raw": raw,
        "amount_krw": "",
        "amount_unit": unit,
        "numeric_value": value,
        "numeric_unit": unit,
        "comparison": "",
        "answer_policy": rule["answer_policy"],
        "budget_answer_enabled": False,
        "eligibility_answer_enabled": bool(rule["eligibility_answer_enabled"]),
        "payment_answer_enabled": bool(rule["payment_answer_enabled"]),
        "source_origin": text_source,
        "evidence_snippet": snippet_at(text, match.start(), match.end(), radius=190),
        "comment": rule["comment"],
    }


def dedupe_non_project_facts(facts: list[dict[str, Any]], max_items: int = 80) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = (
            fact.get("fact_type"), fact.get("amount_subtype"), fact.get("amount_raw"),
            fact.get("amount_krw"), fact.get("numeric_value"), compact_norm(fact.get("evidence_snippet", "")[:220], False),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
        if len(deduped) >= max_items:
            break
    return deduped


def extract_non_project_amount_facts(text: str, text_source: str) -> list[dict[str, Any]]:
    if not text:
        return []
    facts: list[dict[str, Any]] = []
    for rule in NON_PROJECT_AMOUNT_RULES:
        for pattern in rule["patterns"]:
            for match in re.finditer(pattern, text, flags=re.I):
                fact = make_non_project_amount_fact(rule, match, text, text_source)
                if fact:
                    facts.append(fact)
    for rule in NON_PROJECT_PERCENT_RULES:
        for pattern in rule["patterns"]:
            for match in re.finditer(pattern, text, flags=re.I):
                fact = make_non_project_percent_fact(rule, match, text, text_source)
                if fact:
                    facts.append(fact)
    # Keep fact types aligned with current chunks_v2 conventions:
    # threshold_budget / reference_amount / payment_terms are route-only or intent-specific, never project budget.
    return dedupe_non_project_facts(facts)


def facts_json(facts: list[dict[str, Any]]) -> str:
    return json.dumps(facts, ensure_ascii=False, sort_keys=True)


def facts_by_type(facts: list[dict[str, Any]], fact_type: str) -> list[dict[str, Any]]:
    return [fact for fact in facts if fact.get("fact_type") == fact_type]


def title_similarity(a: str, b: str) -> float:
    a1, b1 = compact_norm(a, False), compact_norm(b, False)
    a2, b2 = compact_norm(a, True), compact_norm(b, True)
    scores = []
    for x, y in [(a1, b1), (a2, b2)]:
        if x and y:
            scores.append(SequenceMatcher(None, x, y).ratio())
            if x in y or y in x:
                scores.append(0.92)
    return max(scores) if scores else 0.0


def load_raw_master(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        return {}


def agency_in_text(agency: str, text: str, source_file: str = "") -> bool:
    norm_agency = compact_norm(agency, False)
    if not norm_agency:
        return False
    norm_text_head = compact_norm((source_file or "") + " " + text[:5000], False)
    # City hall aliases: 화성시청 vs 경기도 화성시.
    norm_agency_short = norm_agency.replace("경기도", "").replace("광역시", "").replace("특별시", "").replace("조달청", "")
    if norm_agency in norm_text_head or (norm_agency_short and norm_agency_short in norm_text_head):
        return True
    return False


def has_role_mismatch(source_name: str, g2b_title: str, text: str) -> bool:
    source_context = normalize_text(source_name + " " + text[:5000]).lower()
    g2b = normalize_text(g2b_title).lower()
    # Same base project but different procurement unit, such as main system build vs PMO/audit/privacy-impact assessment.
    sensitive_roles = ["감리", "pmo", "PMO", "개인정보영향평가", "영향평가"]
    for role in sensitive_roles:
        if role.lower() in g2b and role.lower() not in source_context:
            return True
    return False


def validate_g2b_match(row: dict[str, str], text: str) -> tuple[bool, str, float, bool]:
    raw = load_raw_master(row.get("raw_master_json", ""))
    g2b_title = row.get("g2b_title", "")
    source_name = row.get("normalized_project_name", "") or row.get("source_file", "")
    title_sim = title_similarity(source_name, g2b_title)
    agencies = [raw.get("공고기관", ""), raw.get("수요기관", "")]
    agency_ok = any(agency_in_text(a, text, row.get("source_file", "")) for a in agencies)
    title_in_text = bool(compact_norm(g2b_title, True) and compact_norm(g2b_title, True) in compact_norm(text[:12000], True))
    source_title_in_g2b = title_sim >= 0.86
    role_mismatch = has_role_mismatch(source_name, g2b_title, text)
    # Title-only matching is intentionally disallowed because many RFPs share generic names such as ISP/BPR/통합관리시스템.
    valid = bool(g2b_title and agency_ok and (source_title_in_g2b or title_in_text) and not role_mismatch)
    if not g2b_title:
        reason = "g2b_notice_missing"
    elif role_mismatch:
        reason = "rejected_g2b_notice_role_mismatch"
    elif not agency_ok:
        reason = "rejected_g2b_notice_agency_not_in_original"
    elif not (source_title_in_g2b or title_in_text):
        reason = "rejected_g2b_notice_title_not_strict_enough"
    else:
        reason = "valid_g2b_notice_match"
    return valid, reason, round(title_sim, 4), agency_ok


def g2b_amount_candidate(row: dict[str, str]) -> AmountCandidate | None:
    allocated = to_int_amount(row.get("g2b_allocated_budget"))
    if allocated:
        return AmountCandidate(
            value=format_krw(allocated), value_krw=allocated, label="g2b_allocated_budget",
            role="project_budget", confidence="medium", source="g2b_notice_detail",
            snippet=(
                f"나라장터 상세 관련금액: 배정예산={row.get('g2b_allocated_budget','')}, "
                f"추정가격={row.get('g2b_estimated_price','')}, 부가가치세={row.get('g2b_vat','')}, 기타금액={row.get('g2b_other_amount','')}"
            ),
            comment="RFP 원문 사업예산 미확인. 엄격 매칭된 나라장터 상세의 배정예산을 사업예산 보강값으로 사용",
            original_amount_text=row.get("g2b_allocated_budget", ""),
        )
    return None


def reconcile(project_root: Path, input_csv: Path, output_csv: Path, audit_csv: Path, report_json: Path) -> None:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        original_fields = reader.fieldnames or []

    extra_fields = [
        "previous_final_project_budget", "strict_final_project_budget", "budget_value_role", "budget_comment",
        "budget_decision_source", "budget_confidence", "budget_original_amount_text", "budget_normalized_amount_krw",
        "rfp_strict_project_budget", "rfp_strict_project_budget_original_amount_text", "rfp_strict_project_budget_normalized_amount_krw",
        "rfp_strict_project_budget_label", "rfp_strict_project_budget_snippet",
        "rfp_base_amount", "rfp_base_amount_original_amount_text", "rfp_base_amount_normalized_amount_krw",
        "rfp_base_amount_comment", "rfp_estimated_price_strict", "rfp_estimated_price_original_amount_text",
        "rfp_estimated_price_normalized_amount_krw",
        "g2b_match_valid", "g2b_match_validation_reason", "g2b_title_similarity", "g2b_agency_in_original_text",
        "non_project_amount_facts_json", "non_project_amount_fact_count", "threshold_budget_facts_json",
        "threshold_budget_fact_count", "reference_amount_facts_json", "reference_amount_fact_count",
        "payment_terms_facts_json", "payment_terms_fact_count", "non_project_amount_fact_types",
        "rejected_previous_final_project_budget", "rejected_previous_budget_reason", "strict_text_source", "strict_text_length",
    ]
    fields = list(original_fields)
    for field in extra_fields:
        if field not in fields:
            fields.append(field)

    audit_rows: list[dict[str, Any]] = []
    stats = Counter()

    for row in rows:
        old_final = row.get("final_project_budget", "")
        text, text_source = extract_source_text(project_root, row)
        rfp_budget, all_project_candidates, base_amount, estimated_price = select_rfp_budget(text, text_source)
        non_project_facts = extract_non_project_amount_facts(text, text_source)
        threshold_facts = facts_by_type(non_project_facts, "threshold_budget")
        reference_facts = facts_by_type(non_project_facts, "reference_amount")
        payment_facts = facts_by_type(non_project_facts, "payment_terms")
        g2b_valid, g2b_reason, title_sim, agency_ok = validate_g2b_match(row, text)
        g2b_candidate = g2b_amount_candidate(row) if g2b_valid else None

        selected: AmountCandidate | None = None
        if rfp_budget:
            selected = rfp_budget
            selected.source = "rfp_body_strict"
        elif g2b_candidate:
            selected = g2b_candidate
        else:
            selected = None

        row["previous_final_project_budget"] = old_final
        row["strict_text_source"] = text_source
        row["strict_text_length"] = str(len(text))
        row["non_project_amount_facts_json"] = facts_json(non_project_facts)
        row["non_project_amount_fact_count"] = str(len(non_project_facts))
        row["threshold_budget_facts_json"] = facts_json(threshold_facts)
        row["threshold_budget_fact_count"] = str(len(threshold_facts))
        row["reference_amount_facts_json"] = facts_json(reference_facts)
        row["reference_amount_fact_count"] = str(len(reference_facts))
        row["payment_terms_facts_json"] = facts_json(payment_facts)
        row["payment_terms_fact_count"] = str(len(payment_facts))
        row["non_project_amount_fact_types"] = "|".join(sorted({fact.get("fact_type", "") for fact in non_project_facts if fact.get("fact_type")}))
        stats["non_project_amount_fact_count"] += len(non_project_facts)
        stats["threshold_budget_fact_count"] += len(threshold_facts)
        stats["reference_amount_fact_count"] += len(reference_facts)
        stats["payment_terms_fact_count"] += len(payment_facts)
        row["rfp_strict_project_budget"] = rfp_budget.value if rfp_budget else ""
        row["rfp_strict_project_budget_original_amount_text"] = rfp_budget.original_amount_text if rfp_budget else ""
        row["rfp_strict_project_budget_normalized_amount_krw"] = str(rfp_budget.value_krw) if rfp_budget and rfp_budget.value_krw is not None else ""
        row["rfp_strict_project_budget_label"] = rfp_budget.label if rfp_budget else ""
        row["rfp_strict_project_budget_snippet"] = rfp_budget.snippet if rfp_budget else ""
        row["rfp_base_amount"] = base_amount.value if base_amount else ""
        row["rfp_base_amount_original_amount_text"] = base_amount.original_amount_text if base_amount else ""
        row["rfp_base_amount_normalized_amount_krw"] = str(base_amount.value_krw) if base_amount and base_amount.value_krw is not None else ""
        row["rfp_base_amount_comment"] = base_amount.comment if base_amount else ""
        row["rfp_estimated_price_strict"] = estimated_price.value if estimated_price else ""
        row["rfp_estimated_price_original_amount_text"] = estimated_price.original_amount_text if estimated_price else ""
        row["rfp_estimated_price_normalized_amount_krw"] = str(estimated_price.value_krw) if estimated_price and estimated_price.value_krw is not None else ""
        row["g2b_match_valid"] = "true" if g2b_valid else "false"
        row["g2b_match_validation_reason"] = g2b_reason
        row["g2b_title_similarity"] = str(title_sim)
        row["g2b_agency_in_original_text"] = "true" if agency_ok else "false"

        if selected:
            strict_value = selected.value
            row["final_project_budget"] = strict_value
            row["strict_final_project_budget"] = strict_value
            row["budget_original_amount_text"] = selected.original_amount_text
            row["budget_normalized_amount_krw"] = str(selected.value_krw) if selected.value_krw is not None else ""
            row["budget_value_role"] = "project_budget"
            row["budget_comment"] = selected.comment
            row["budget_decision_source"] = selected.source
            row["budget_confidence"] = selected.confidence
            stats[f"selected_{selected.source}"] += 1
        else:
            row["final_project_budget"] = ""
            row["strict_final_project_budget"] = ""
            row["budget_original_amount_text"] = ""
            row["budget_normalized_amount_krw"] = ""
            if base_amount and not rfp_budget:
                row["budget_value_role"] = "base_amount_not_project_budget"
                row["budget_comment"] = base_amount.comment
            elif estimated_price and not rfp_budget:
                row["budget_value_role"] = "estimated_price_not_project_budget"
                row["budget_comment"] = estimated_price.comment
            else:
                row["budget_value_role"] = "unknown_or_missing"
                row["budget_comment"] = "원문과 엄격 매칭된 나라장터 상세에서 사업예산을 확정하지 못해 공란 유지"
            row["budget_decision_source"] = "not_promoted"
            row["budget_confidence"] = "missing_or_uncertain"
            stats["selected_blank"] += 1

        # If the G2B match itself is invalid, clear G2B-derived operational fields in strict output to prevent downstream noise.
        if not g2b_valid:
            if any(row.get(k, "") for k in ["g2b_allocated_budget", "g2b_estimated_price", "g2b_vat", "g2b_other_amount", "g2b_title"]):
                row["rejected_previous_budget_reason"] = (row.get("rejected_previous_budget_reason", "") + ";" if row.get("rejected_previous_budget_reason") else "") + g2b_reason
            for key in ["g2b_allocated_budget", "g2b_estimated_price", "g2b_vat", "g2b_other_amount", "raw_master_json"]:
                row[key] = ""
            # Clear notice/deadline only if they came from the rejected G2B/master match and not from RFP body.
            if row.get("deadline_source_origin") != "rfp_body_strong_label":
                row["final_bid_deadline"] = row.get("rfp_bid_deadline", "")
            row["g2b_title"] = ""
            row["bid_notice_no"] = ""
            row["bid_notice_ord"] = ""

        if old_final and row["final_project_budget"] != old_final:
            row["rejected_previous_final_project_budget"] = old_final
            if not row.get("rejected_previous_budget_reason"):
                row["rejected_previous_budget_reason"] = "previous_final_project_budget_failed_strict_reconciliation"
            stats["changed_existing_final_project_budget"] += 1
            audit_rows.append({
                "source_file": row.get("source_file", ""),
                "previous_final_project_budget": old_final,
                "strict_final_project_budget": row["final_project_budget"],
                "budget_value_role": row["budget_value_role"],
                "budget_decision_source": row["budget_decision_source"],
                "budget_comment": row["budget_comment"],
                "rejected_previous_budget_reason": row.get("rejected_previous_budget_reason", ""),
                "g2b_match_valid": row["g2b_match_valid"],
                "g2b_match_validation_reason": row["g2b_match_validation_reason"],
                "g2b_title_similarity": row["g2b_title_similarity"],
                "g2b_agency_in_original_text": row["g2b_agency_in_original_text"],
                "budget_original_amount_text": row.get("budget_original_amount_text", ""),
                "budget_normalized_amount_krw": row.get("budget_normalized_amount_krw", ""),
                "rfp_strict_project_budget_snippet": row.get("rfp_strict_project_budget_snippet", ""),
                "rfp_base_amount": row.get("rfp_base_amount", ""),
                "rfp_base_amount_original_amount_text": row.get("rfp_base_amount_original_amount_text", ""),
                "rfp_base_amount_normalized_amount_krw": row.get("rfp_base_amount_normalized_amount_krw", ""),
            })

        # Clear stale extraction confidence/source fields that no longer represent strict final if needed.
        row["amount_source_origin"] = row["budget_decision_source"] if row["final_project_budget"] else ""
        row["amount_evidence_label"] = row.get("rfp_strict_project_budget_label", "") if rfp_budget else ("g2b_allocated_budget" if g2b_candidate and selected == g2b_candidate else "")
        row["amount_evidence_snippet"] = selected.snippet if selected else ""
        if row["final_project_budget"]:
            row["extraction_confidence"] = row["budget_confidence"]
        else:
            row["extraction_confidence"] = "amount_missing_or_uncertain"

    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    audit_fields = [
        "source_file", "previous_final_project_budget", "strict_final_project_budget", "budget_value_role",
        "budget_decision_source", "budget_comment", "rejected_previous_budget_reason", "g2b_match_valid",
        "g2b_match_validation_reason", "g2b_title_similarity", "g2b_agency_in_original_text",
        "budget_original_amount_text", "budget_normalized_amount_krw",
        "rfp_strict_project_budget_snippet", "rfp_base_amount", "rfp_base_amount_original_amount_text",
        "rfp_base_amount_normalized_amount_krw",
    ]
    with audit_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=audit_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(audit_rows)

    final_count = sum(1 for r in rows if r.get("final_project_budget", "").strip())
    role_counts = Counter(r.get("budget_value_role", "") for r in rows)
    source_counts = Counter(r.get("budget_decision_source", "") for r in rows)
    g2b_valid_count = sum(1 for r in rows if r.get("g2b_match_valid") == "true")
    report = {
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "audit_csv": str(audit_csv),
        "rows": len(rows),
        "final_project_budget_count": final_count,
        "changed_existing_final_project_budget_count": stats["changed_existing_final_project_budget"],
        "g2b_match_valid_count": g2b_valid_count,
        "budget_value_role_counts": dict(role_counts),
        "budget_decision_source_counts": dict(source_counts),
        "non_project_amount_fact_total": stats["non_project_amount_fact_count"],
        "threshold_budget_fact_total": stats["threshold_budget_fact_count"],
        "reference_amount_fact_total": stats["reference_amount_fact_count"],
        "payment_terms_fact_total": stats["payment_terms_fact_count"],
        "stats": dict(stats),
        "policy": "RFP 원문 명시 사업예산 우선. 원문 미확정 시 엄격 매칭된 나라장터 상세 배정예산만 사용. 기초금액/추정가격/자격조건/하한/실적/평가 산식 금액은 final_project_budget 공란 또는 별도 role로 보관. 사업정보/발주금액 기준/사업금액 하한/제안서 보상/입찰가격평가/입찰참가자격 매출·실적 기준은 non_project_amount_facts_json에 threshold_budget/reference_amount/payment_terms로 분류한다.",
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--input", default="data/g2b_notice_enrichment_690_keyless_detail_filled.csv")
    parser.add_argument("--output", default="data/g2b_notice_enrichment_690_strict_budget_reconciled.csv")
    parser.add_argument("--audit-output", default="data/g2b_notice_enrichment_690_strict_budget_reconciled_audit.csv")
    parser.add_argument("--report-output", default="data/g2b_notice_enrichment_690_strict_budget_reconciled_report.json")
    args = parser.parse_args()
    project_root = Path(args.project_root)
    reconcile(
        project_root=project_root,
        input_csv=project_root / args.input,
        output_csv=project_root / args.output,
        audit_csv=project_root / args.audit_output,
        report_json=project_root / args.report_output,
    )

if __name__ == "__main__":
    main()
