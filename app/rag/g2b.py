import re
from typing import Any


NOTICE_PATTERNS = [
    re.compile(r"\b20\d{8,12}(?:-\d{2})?\b"),
    re.compile(r"(?:G2B\s*)?(?:공고번호|입찰공고번호|공고\s*번호)\s*[:：]?\s*([0-9]{10,14}(?:-\d{2})?)"),
]


def _candidate_text(row: dict[str, Any]) -> str:
    meta = row.get("metadata") or {}
    parts = [row.get("chunk_id"), row.get("text")]
    parts.extend(str(value) for value in meta.values() if value is not None)
    return "\n".join(str(part) for part in parts if part)


def extract_notice_numbers(rows: list[dict[str, Any]], limit: int = 5) -> list[str]:
    notices: list[str] = []
    for row in rows:
        text = _candidate_text(row)
        for pattern in NOTICE_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if match.groups() else match.group(0)
                value = value.strip()
                if value and value not in notices:
                    notices.append(value)
                if len(notices) >= limit:
                    return notices
    return notices


def build_manual_lookup_contexts(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    notices = extract_notice_numbers(rows, limit=limit)
    if not notices:
        return []

    first_meta = (rows[0].get("metadata") or {}) if rows else {}
    source_file = first_meta.get("source_file", "")
    project_name = first_meta.get("project_name", "")
    issuer = first_meta.get("issuer", "")
    contexts = []
    for notice in notices:
        contexts.append(
            {
                "notice_number": notice,
                "issuer": issuer,
                "project_name": project_name,
                "source_file": source_file,
                "g2b_url": "https://www.g2b.go.kr/index.jsp",
                "text": (
                    f"문서에서 G2B 공고번호 {notice}를 확인했습니다. "
                    "나라장터에서 해당 공고번호로 직접 조회해 예산/배정금액 첨부 공고를 확인하세요."
                ),
            }
        )
    return contexts


def append_manual_lookup_answer(answer: str, contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return answer
    lines = [answer.rstrip(), "", "문서에서 확인된 나라장터 공고번호로 추가 확인할 수 있습니다."]
    for ctx in contexts:
        lines.append(f"- 공고번호: {ctx['notice_number']}")
    lines.append("- 확인 경로: https://www.g2b.go.kr/index.jsp")
    return "\n".join(lines)
