from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


BUDGET_KEYWORDS = ("금액", "예산", "사업비", "기초금액", "추정가격", "가격", "원")
DATE_KEYWORDS = ("날짜", "기간", "마감", "공고일", "제출", "접수", "입찰일", "계약기간", "기한")
SUBMISSION_KEYWORDS = ("제출서류", "제출 서류", "서류", "제안서", "구비서류", "입찰참가", "첨부")
QUALIFICATION_KEYWORDS = ("자격", "요건", "참가자격", "입찰자격", "제한", "실적")

MONEY_PATTERN = re.compile(
    r"(?:금\s*)?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)\s*(?:원|천원|만원|억원|백만원|KRW|부가세|VAT)|KRW\s*:\s*[0-9]{4,}"
)
DATE_PATTERN = re.compile(
    r"(?:20\d{2}|\d{2})[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}(?:일)?|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}:\d{2}"
)
NOTICE_PATTERN = re.compile(r"[A-Z0-9가-힣]+[-–][A-Z0-9가-힣-]{3,}")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


@dataclass
class GenerationInput:
    question: str
    question_type: str
    prompt: str
    context_text: str
    context_records: list[dict[str, Any]]
    field_candidates: dict[str, list[str]]
    evidence_sentences: list[dict[str, Any]]


def build_generation_input(
    question: str,
    retrieved_contexts: list[dict[str, Any]],
    context_max_chars: int = 1200,
    snippets_per_context: int = 3,
) -> GenerationInput:
    question_type = classify_question(question)
    context_records = [
        _context_record(rank, context, context_max_chars=context_max_chars)
        for rank, context in enumerate(retrieved_contexts, 1)
    ]
    field_candidates = collect_field_candidates(context_records)
    evidence_sentences = collect_evidence_sentences(
        question=question,
        question_type=question_type,
        context_records=context_records,
        snippets_per_context=snippets_per_context,
    )
    context_text = render_context_text(context_records, field_candidates, evidence_sentences)
    prompt = render_prompt(question=question, question_type=question_type, context_text=context_text)
    return GenerationInput(
        question=question,
        question_type=question_type,
        prompt=prompt,
        context_text=context_text,
        context_records=context_records,
        field_candidates=field_candidates,
        evidence_sentences=evidence_sentences,
    )


def classify_question(question: str) -> str:
    text = str(question or "")
    if any(keyword in text for keyword in BUDGET_KEYWORDS):
        return "budget"
    if any(keyword in text for keyword in SUBMISSION_KEYWORDS):
        return "submission_documents"
    if any(keyword in text for keyword in DATE_KEYWORDS):
        return "date_or_period"
    if any(keyword in text for keyword in QUALIFICATION_KEYWORDS):
        return "qualification"
    return "general"


def collect_field_candidates(context_records: list[dict[str, Any]]) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {
        "source_file": [],
        "issuer": [],
        "project_name": [],
        "budget": [],
        "amounts": [],
        "dates": [],
        "notice_like_values": [],
        "section_path": [],
    }
    for record in context_records:
        metadata = record.get("metadata") or {}
        _append_unique(candidates["source_file"], record.get("filename"))
        _append_unique(candidates["issuer"], metadata.get("issuer"))
        _append_unique(candidates["project_name"], metadata.get("project_name"))
        _append_unique(candidates["budget"], metadata.get("budget"))
        _append_unique(candidates["section_path"], metadata.get("section_path"))
        for value in _coerce_list(metadata.get("amounts")):
            _append_unique(candidates["amounts"], value)
        for value in _coerce_list(metadata.get("dates")):
            _append_unique(candidates["dates"], value)

        text = record.get("text") or ""
        for value in _amount_normalization_values(text, metadata=metadata):
            _append_unique(candidates["amounts"], value)
        for value in DATE_PATTERN.findall(text):
            _append_unique(candidates["dates"], value)
        for value in NOTICE_PATTERN.findall(text):
            _append_unique(candidates["notice_like_values"], value)

    return {key: values[:20] for key, values in candidates.items() if values}


def collect_evidence_sentences(
    question: str,
    question_type: str,
    context_records: list[dict[str, Any]],
    snippets_per_context: int = 3,
) -> list[dict[str, Any]]:
    patterns = _evidence_patterns(question, question_type)
    evidence = []
    for record in context_records:
        text = record.get("text") or ""
        sentences = _split_sentences(text)
        selected = []
        for sentence in sentences:
            if any(pattern.search(sentence) for pattern in patterns):
                selected.append(sentence)
            if len(selected) >= snippets_per_context:
                break
        if not selected and sentences:
            selected.append(sentences[0])
        for sentence in selected[:snippets_per_context]:
            evidence.append(
                {
                    "rank": record.get("rank"),
                    "filename": record.get("filename"),
                    "chunk_id": record.get("chunk_id"),
                    "sentence": sentence,
                }
            )
    return evidence[: max(10, snippets_per_context * len(context_records))]


def render_context_text(
    context_records: list[dict[str, Any]],
    field_candidates: dict[str, list[str]],
    evidence_sentences: list[dict[str, Any]],
) -> str:
    parts = []
    parts.append("[검색 문서 요약]")
    for record in context_records:
        metadata = record.get("metadata") or {}
        parts.append(
            "\n".join(
                [
                    f"- rank: {record.get('rank')}",
                    f"  filename: {record.get('filename') or '정보 없음'}",
                    f"  doc_id: {record.get('doc_id') or '정보 없음'}",
                    f"  chunk_id: {record.get('chunk_id') or '정보 없음'}",
                    f"  score: {record.get('score')}",
                    f"  issuer: {metadata.get('issuer') or '정보 없음'}",
                    f"  project_name: {metadata.get('project_name') or '정보 없음'}",
                    f"  budget: {metadata.get('budget') or '정보 없음'}",
                    f"  section_path: {metadata.get('section_path') or '정보 없음'}",
                ]
            )
        )

    if field_candidates:
        parts.append("\n[필드별 후보값]")
        for key, values in field_candidates.items():
            parts.append(f"- {key}: " + "; ".join(map(str, values[:12])))

    if evidence_sentences:
        parts.append("\n[근거 문장 후보]")
        for item in evidence_sentences:
            parts.append(
                f"- rank {item.get('rank')} | {item.get('filename')} | {item.get('chunk_id')}: {item.get('sentence')}"
            )

    parts.append("\n[검색 chunk 원문]")
    for record in context_records:
        parts.append(
            f"\n--- Context rank {record.get('rank')} | {record.get('filename')} | {record.get('chunk_id')} ---\n"
            f"{record.get('text') or ''}"
        )
    return "\n".join(parts)


def render_prompt(question: str, question_type: str, context_text: str) -> str:
    type_rule = _type_specific_rule(question_type)
    return f"""너는 RFP 문서 기반 QA assistant다.

반드시 지켜야 할 규칙:
1. 제공된 Context 안의 정보만 사용한다.
2. Context에 없으면 추측하지 말고 "문서에서 확인할 수 없습니다"라고 답한다.
3. 금액, 날짜, 기간, 공고번호는 원문 표현을 우선 보존한다.
4. 답변에는 반드시 근거 문서명과 근거 문장을 함께 제시한다.
5. 서로 다른 후보가 있으면 하나로 단정하지 말고 후보를 나눠 말한다.
6. 기초금액, 추정가격, 사업예산, 사업비는 서로 다를 수 있으므로 문서 표현을 구분한다.
7. 답변은 한국어로 작성한다.

질문 유형: {question_type}
질문 유형별 추가 규칙:
{type_rule}

답변 형식:
[답변]
- 질문에 대한 답을 1~5문장 또는 짧은 bullet로 작성

[근거]
- 문서명: ...
- 근거 문장: "..."

[주의/불확실성]
- 후보가 여러 개이거나 확인 불가한 부분이 있으면 작성

[Question]
{question}

[Context]
{context_text}
""".strip()


def _context_record(rank: int, context: dict[str, Any], context_max_chars: int) -> dict[str, Any]:
    metadata = context.get("metadata") or {}
    text = str(context.get("text") or "")
    if context_max_chars > 0:
        text = text[:context_max_chars]
    text = _append_amount_normalization_lines(text, metadata=metadata)
    return {
        "rank": rank,
        "filename": context.get("filename") or metadata.get("source_file"),
        "doc_id": context.get("doc_id"),
        "chunk_id": context.get("chunk_id"),
        "score": context.get("score"),
        "metadata": metadata,
        "text": text,
    }


def _type_specific_rule(question_type: str) -> str:
    if question_type == "budget":
        return "- 금액 후보값과 금액 근거 문장을 우선 확인한다. 사업예산/기초금액/추정가격을 섞어 쓰지 않는다."
    if question_type == "submission_documents":
        return "- 제출서류, 제안서, 입찰참가서류 관련 근거 문장을 우선 확인한다. 서류명은 중복 없이 정리한다."
    if question_type == "date_or_period":
        return "- 날짜와 기간 후보값을 우선 확인한다. 접수마감, 제출마감, 계약기간을 구분한다."
    if question_type == "qualification":
        return "- 참가자격/제한요건/실적요건 관련 근거 문장을 우선 확인한다."
    return "- 질문에 직접 답하는 문장과 메타데이터를 함께 확인한다."


def _evidence_patterns(question: str, question_type: str) -> list[re.Pattern[str]]:
    words = []
    if question_type == "budget":
        words.extend(BUDGET_KEYWORDS)
        extra = [MONEY_PATTERN.pattern]
    elif question_type == "submission_documents":
        words.extend(SUBMISSION_KEYWORDS)
        extra = []
    elif question_type == "date_or_period":
        words.extend(DATE_KEYWORDS)
        extra = [DATE_PATTERN.pattern]
    elif question_type == "qualification":
        words.extend(QUALIFICATION_KEYWORDS)
        extra = []
    else:
        words.extend(_question_terms(question))
        extra = []
    escaped = [re.escape(word) for word in words if word]
    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in escaped + extra]
    return patterns or [re.compile(r".")]


def _question_terms(question: str) -> list[str]:
    terms = re.findall(r"[0-9A-Za-z가-힣]{2,}", question or "")
    stopwords = {"무엇", "얼마", "어떤", "알려", "인가", "입니까", "해당"}
    return [term for term in terms if term not in stopwords][:8]


def _split_sentences(text: str) -> list[str]:
    sentences = []
    for part in SENTENCE_SPLIT.split(text or ""):
        sentence = re.sub(r"\s+", " ", part).strip()
        if sentence:
            sentences.append(sentence[:500])
    return sentences


def _append_unique(values: list[str], value: Any) -> None:
    if value in (None, "", []):
        return
    text = str(value).strip()
    if text and text not in values:
        values.append(text)


def _amount_normalization_values(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_items: int = 8,
) -> list[str]:
    items = _amount_normalization_items(text, metadata=metadata, max_items=max_items)
    return [f"{item['raw']} -> {_format_won(item['won'])}" for item in items]


def _append_amount_normalization_lines(text: str, *, metadata: dict[str, Any] | None = None) -> str:
    if "[금액 정규화]" in str(text or ""):
        return str(text or "")
    items = _amount_normalization_items(str(text or ""), metadata=metadata, max_items=8)
    if not items:
        return str(text or "")
    lines = ["[금액 정규화] 원문 금액과 원 단위 환산값"]
    for item in items:
        lines.append(f"- 원문: {item['raw']} | 정규화: {_format_won(item['won'])} | KRW: {item['won']}")
    return "\n".join(lines + [str(text or "")])


def _amount_normalization_items(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    values: list[dict[str, Any]] = []
    for raw_key, won_key in (
        ("final_budget", "final_budget_krw"),
        ("budget", "budget_krw"),
        ("budget_text", "budget_krw"),
    ):
        won = _safe_int(metadata.get(won_key))
        raw = metadata.get(raw_key)
        if won:
            values.append({"raw": str(raw or _format_won(won)), "won": won})
        elif raw:
            converted = _amount_to_won(str(raw))
            if converted:
                values.append({"raw": str(raw), "won": converted})
    scan_text = _strip_amount_normalization_lines(str(text or ""))
    for match in MONEY_PATTERN.finditer(scan_text):
        raw = match.group(0)
        won = _amount_to_won(raw)
        if won:
            values.append({"raw": raw, "won": won})
    return _dedupe_amount_values(values, max_items=max_items)


def _dedupe_amount_values(values: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        raw = str(value.get("raw") or "").strip()
        won = _safe_int(value.get("won"))
        if not raw or not won:
            continue
        key = (re.sub(r"\s+", "", raw).casefold(), won)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"raw": raw, "won": won})
        if len(deduped) >= max_items:
            break
    return deduped


def _amount_to_won(raw: str) -> int | None:
    value = str(raw or "").replace(",", "").replace(" ", "")
    number_match = re.search(r"\d+(?:\.\d+)?", value)
    if not number_match:
        return None
    number = float(number_match.group(0))
    if "조" in value:
        number *= 1_000_000_000_000
    elif "억" in value:
        number *= 100_000_000
    elif "백만원" in value or "백만" in value:
        number *= 1_000_000
    elif "천만원" in value or "천만" in value:
        number *= 10_000_000
    elif "만원" in value:
        number *= 10_000
    elif "천원" in value:
        number *= 1_000
    return int(round(number))


def _safe_int(value: Any) -> int:
    try:
        text = re.sub(r"[^0-9.-]", "", str(value or ""))
        if not text:
            return 0
        return int(round(float(text)))
    except (TypeError, ValueError):
        return 0


def _format_won(value: Any) -> str:
    try:
        return f"{int(round(float(value))):,}원"
    except (TypeError, ValueError):
        return str(value)


def _strip_amount_normalization_lines(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("[금액 정규화]") or stripped.startswith("- 원문:"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _coerce_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]
