from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
import hashlib
import json
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

import rfp_parsing_v1_v2_lib as rfp


CHUNK_MAX_CHARS = rfp.CHUNK_MAX_CHARS
CHUNK_OVERLAP = rfp.CHUNK_OVERLAP
P4_125_LIMIT = 125
P4_125_OUTPUT_NAME = "parsing_p4_hwpx_125"
P4_125_TARGET_DOCS = 125
P4_125_FILLER_DOCS = 85  # current deduplicated eval scope: 40 eval docs + 85 fillers
P4_125_HARD_DISTRACTOR_TARGET = 12
PARSER_VERSION = "p4_hwpx_precision_v2026_05_20"

FACT_TYPE_ALIASES = {
    "document_summary": "문서요약/사업개요/공고요약",
    "budget": "사업금액/사업비/예산/추정가격/배정예산",
    "duration": "사업기간/과업기간/수행기간/계약기간/유지보수기간",
    "bid_deadline": "입찰마감일/마감일시/제출마감/접수마감",
    "submission_documents": "제출서류/구비서류/입찰서류/제안서류",
    "submission_logistics": "제안서 제출/제출방법/제출장소/제출처/온라인제출/방문제출",
    "eligibility": "입찰참가자격/참가자격/자격요건/공동수급/실적/인증",
    "business_type": "사업유형/업무분류/과업유형/구축/운영/유지관리/고도화",
}

HIGH_SIGNAL_TABLE_KEYWORDS = [
    "평가기준", "평가 기준", "배점", "기술평가", "정량평가", "정성평가", "심사기준",
    "제출서류", "구비서류", "제안서", "제출방법", "제출장소", "제출처",
    "요구사항", "요구사항명", "기능요구", "성능요구", "보안요구", "사업범위", "과업범위",
    "입찰참가자격", "참가자격", "자격요건", "공동수급", "하도급", "실적", "인증",
    "사업금액", "사업비", "예산", "추정가격", "기초금액", "사업기간", "수행기간", "계약기간",
]

LOW_SIGNAL_TABLE_KEYWORDS = [
    "목차", "차례", "개정이력", "문서정보", "결재", "표지", "양식", "서식번호",
]

BUSINESS_TYPE_BUCKETS = [
    "유지관리", "고도화", "구축", "운영", "데이터/AI", "보안", "클라우드", "홈페이지/포털", "컨설팅/감리", "기타",
]

G2B_MASTER_FILENAME = "g2b_master_cleaned.csv"
G2B_MATCH_THRESHOLD = 72
G2B_AMBIGUOUS_MARGIN = 6
G2B_KIND_PRIORITY = {
    "변경공고": 5,
    "재공고(재입찰)": 4,
    "재공고": 4,
    "긴급공고": 3,
    "등록공고(재입찰)": 2,
    "등록공고": 1,
}
G2B_METADATA_KEYS = [
    "g2b_match_status",
    "g2b_match_score",
    "g2b_match_reason",
    "g2b_candidate_count",
    "g2b_active_candidate_count",
    "g2b_cancelled_candidate_count",
    "g2b_conflict_status",
    "g2b_notice_id",
    "g2b_notice_base",
    "g2b_notice_revision",
    "g2b_notice_kind",
    "g2b_is_cancelled",
    "g2b_title",
    "g2b_notice_agency",
    "g2b_demand_agency",
    "g2b_bid_deadline",
    "g2b_bid_deadline_source",
    "g2b_cancelled_notice_ids",
    "g2b_ambiguous_notice_ids",
]
P4_RETRIEVAL_METADATA_KEYS = [
    "g2b_notice_id",
    "g2b_bid_deadline",
]
P4_SOURCE_AUDIT_METADATA_KEYS = [
    "final_notice_id",
    "notice_id_status",
    "final_budget",
    "final_budget_krw",
    "final_budget_status",
    "final_project_duration",
    "final_bid_deadline",
    "bid_deadline_status",
    *G2B_METADATA_KEYS,
]


def sha1_short(text: str, n: int = 12) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:n]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def truncate(text: str, max_chars: int = 500) -> str:
    text = normalize_space(text)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + " ..."


def as_scalar(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(v) for v in value if str(v).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def section_to_text(section_path) -> str:
    if isinstance(section_path, str):
        return section_path
    return " > ".join(str(x) for x in (section_path or []) if str(x).strip())


def make_doc_id(source_file: str) -> str:
    stable_name = str(source_file or "").strip()
    return f"doc_{sha1_short(stable_name, 12)}"


def make_doc_key(source_file: str) -> str:
    return rfp.normalize_doc_name(source_file)


def compact_match_text(text: str) -> str:
    text = strip_project_prefixes(rfp.normalize_doc_name(text))
    text = text.lower()
    text = re.sub(r"[\s\[\]\(\){}【】「」『』·ㆍ,._\-~/\\\\:;]+", "", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def safe_filename_token(text: str, limit: int = 48) -> str:
    token = re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(text or "")).strip("_")
    return token[:limit] or "item"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(rfp.to_jsonable(row), ensure_ascii=False, separators=(",", ":")) + "\n")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":", 1)[-1]


def child_by_local(elem: ET.Element, name: str) -> ET.Element | None:
    for child in list(elem):
        if local_name(child.tag) == name:
            return child
    return None


def iter_text_no_tables(elem: ET.Element):
    if local_name(elem.tag) == "tbl":
        return
    if local_name(elem.tag) == "t" and elem.text:
        yield elem.text
    for child in list(elem):
        yield from iter_text_no_tables(child)


def paragraph_text_no_tables(p_elem: ET.Element) -> str:
    return normalize_space("".join(iter_text_no_tables(p_elem)))


def paragraph_text(elem: ET.Element) -> str:
    parts = []
    for node in elem.iter():
        if local_name(node.tag) == "t" and node.text:
            parts.append(node.text)
    return normalize_space("".join(parts))


def cell_text(tc_elem: ET.Element) -> str:
    paras = []
    for p in tc_elem.iter():
        if local_name(p.tag) == "p":
            text = paragraph_text(p)
            if text:
                paras.append(text)
    if paras:
        return normalize_space(" / ".join(paras))
    return paragraph_text(tc_elem)


def parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def infer_row_type(row: dict, col_count: int, is_first_nonblank: bool) -> str:
    cells = row.get("cells", [])
    texts = [c.get("text", "").strip() for c in cells if c.get("text", "").strip()]
    if not texts:
        return "blank"
    joined = " ".join(texts)
    if len(texts) == 1:
        only = texts[0]
        max_colspan = max((c.get("colspan", 1) for c in cells if c.get("text", "").strip()), default=1)
        if only.startswith(("※", "*", "주)", "주 :", "비고")):
            return "note"
        if max_colspan >= max(2, col_count - 1) or len(only) <= 80:
            return "group_title"
    header_terms = ["구분", "항목", "내용", "평가", "배점", "비고", "일자", "제출", "서류", "자격", "금액", "장비명", "용도", "기본사양", "건수"]
    short_ratio = sum(1 for t in texts if len(t) <= 30) / max(1, len(texts))
    has_header_term = any(term in joined for term in header_terms)
    has_many_numbers = sum(bool(re.search(r"\d", t)) for t in texts) >= max(2, len(texts) // 2)
    if (is_first_nonblank and len(texts) >= 2 and short_ratio >= 0.6) or (has_header_term and not has_many_numbers):
        return "header_candidate"
    if len(joined) <= 12 and len(texts) <= 2:
        return "group_title"
    return "body"


def infer_columns(rows: list[dict], col_count: int) -> list[str]:
    for row in rows:
        if row.get("row_type") != "header_candidate":
            continue
        values = [""] * max(1, col_count)
        for cell in row.get("cells", []):
            text = cell.get("text", "").strip()
            col = cell.get("col", 0)
            if text and 0 <= col < len(values):
                values[col] = text
        columns = [v or f"col_{idx + 1}" for idx, v in enumerate(values)]
        if sum(1 for v in columns if not v.startswith("col_")) >= 2:
            return columns
    return [f"col_{idx + 1}" for idx in range(max(1, col_count))]


def make_table_body_text(section_path: list[str], rows: list[dict], columns: list[str], shape: dict) -> str:
    section = section_to_text(section_path) or "문서 시작"
    lines = [f"[표 섹션: {section} | rows: {shape.get('row_count', 0)} | cols: {shape.get('col_count', 0)}]"]
    if columns:
        lines.append("컬럼: " + " | ".join(columns[:20]))
    for row in rows:
        row_type = row.get("row_type")
        if row_type in {"blank", "layout_noise"}:
            continue
        texts = [c.get("text", "").strip() for c in row.get("cells", []) if c.get("text", "").strip()]
        if not texts:
            continue
        if row_type == "group_title":
            lines.append("그룹: " + " / ".join(texts))
            continue
        if row_type == "header_candidate":
            continue
        pairs = []
        for cell in row.get("cells", []):
            text = cell.get("text", "").strip()
            if not text:
                continue
            col = cell.get("col", 0)
            col_name = columns[col] if 0 <= col < len(columns) else f"col_{col + 1}"
            pairs.append(f"{col_name}: {text}")
        row_text = " | ".join(pairs) if pairs else " / ".join(texts)
        if row.get("row_group"):
            row_text = f"row_group: {row['row_group']} | {row_text}"
        if row_text:
            lines.append(row_text)
    return "\n".join(lines)


def parse_hwpx_table(tbl_elem: ET.Element, table_seq: int, section_path: list[str]) -> dict:
    attr_col_count = parse_int(tbl_elem.attrib.get("colCnt"), 0)
    attr_row_count = parse_int(tbl_elem.attrib.get("rowCnt"), 0)
    row_map: dict[int, list[dict]] = defaultdict(list)
    fallback_row = 0
    for tr in [x for x in list(tbl_elem) if local_name(x.tag) == "tr"]:
        fallback_col = 0
        for tc in [x for x in list(tr) if local_name(x.tag) == "tc"]:
            addr = child_by_local(tc, "cellAddr")
            span = child_by_local(tc, "cellSpan")
            row_addr = parse_int(addr.attrib.get("rowAddr"), fallback_row) if addr is not None else fallback_row
            col_addr = parse_int(addr.attrib.get("colAddr"), fallback_col) if addr is not None else fallback_col
            rowspan = parse_int(span.attrib.get("rowSpan"), 1) if span is not None else 1
            colspan = parse_int(span.attrib.get("colSpan"), 1) if span is not None else 1
            text = cell_text(tc)
            row_map[row_addr].append({
                "row": row_addr,
                "col": col_addr,
                "rowspan": rowspan,
                "colspan": colspan,
                "text": text,
            })
            fallback_col += max(1, colspan)
        fallback_row += 1
    if not row_map:
        return {}
    col_count = attr_col_count or max((cell["col"] + cell.get("colspan", 1) for cells in row_map.values() for cell in cells), default=0)
    row_count = attr_row_count or (max(row_map) + 1)
    rows = []
    first_nonblank_seen = False
    current_group = None
    for row_index in range(row_count):
        cells = sorted(row_map.get(row_index, []), key=lambda c: c.get("col", 0))
        row = {"row_index": row_index, "cells": cells}
        is_nonblank = any(c.get("text", "").strip() for c in cells)
        row["row_type"] = infer_row_type(row, col_count, is_nonblank and not first_nonblank_seen)
        if is_nonblank and not first_nonblank_seen:
            first_nonblank_seen = True
        if row["row_type"] == "group_title":
            texts = [c.get("text", "").strip() for c in cells if c.get("text", "").strip()]
            current_group = " / ".join(texts) if texts else current_group
            row["row_group"] = current_group
        elif row["row_type"] == "body":
            row["row_group"] = current_group
        else:
            row["row_group"] = None
        rows.append(row)
    merged_cell_count = sum(1 for cells in row_map.values() for c in cells if c.get("rowspan", 1) > 1 or c.get("colspan", 1) > 1)
    shape = {
        "row_count": row_count,
        "col_count": col_count,
        "cell_count": sum(len(cells) for cells in row_map.values()),
        "merged_cell_count": merged_cell_count,
    }
    columns = infer_columns(rows, col_count)
    body_text = make_table_body_text(section_path, rows, columns, shape)
    if len(normalize_space(body_text)) < 20:
        return {}
    return {
        "table_seq": table_seq,
        "section_path": list(section_path),
        "table_shape": shape,
        "columns_candidate": columns,
        "rows": rows,
        "body_text": body_text,
    }


def extract_hwpx_structured(path: str | Path) -> dict:
    path = Path(path)
    all_lines = []
    non_table_lines = []
    tables = []
    current_section = ["문서 시작"]
    table_seq = 0
    try:
        with zipfile.ZipFile(path) as zf:
            section_names = sorted(n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml"))
            for section_name in section_names:
                root = ET.fromstring(zf.read(section_name))
                for elem in root:
                    if local_name(elem.tag) != "p":
                        continue
                    text = paragraph_text_no_tables(elem)
                    if text:
                        non_table_lines.append(text)
                        all_lines.append(text)
                        if rfp.is_probable_heading(text):
                            current_section = [text]
                    for tbl in elem.iter():
                        if local_name(tbl.tag) != "tbl":
                            continue
                        table_seq += 1
                        parsed = parse_hwpx_table(tbl, table_seq, current_section)
                        if parsed:
                            tables.append(parsed)
                            all_lines.append(parsed["body_text"])
        raw_text = "\n".join(all_lines)
        non_table_text = "\n".join(non_table_lines)
        clean_text = rfp.remove_hwp_garbage(raw_text)
        non_table_clean_text = rfp.remove_hwp_garbage(non_table_text)
        return {
            "parser": "hwpx_zip_xml_table_aware",
            "filename": path.name,
            "path": str(path),
            "raw_text": raw_text,
            "clean_text": clean_text,
            "non_table_clean_text": non_table_clean_text,
            "tables": tables,
            "raw_char_len": len(raw_text),
            "clean_char_len": len(clean_text),
            "non_table_clean_char_len": len(non_table_clean_text),
            "table_count": len(tables),
            "image_count": len([n for n in zipfile.ZipFile(path).namelist() if n.lower().startswith(("bindata/", "bindata\\"))]),
            "parser_status": "success",
            "error": "",
        }
    except Exception as exc:
        return {
            "parser": "hwpx_zip_xml_table_aware",
            "filename": path.name,
            "path": str(path),
            "raw_text": "",
            "clean_text": "",
            "non_table_clean_text": "",
            "tables": [],
            "raw_char_len": 0,
            "clean_char_len": 0,
            "non_table_clean_char_len": 0,
            "table_count": 0,
            "image_count": 0,
            "parser_status": "failed",
            "error": repr(exc),
        }


def build_hwpx_lookup(hwpx_dir: Path) -> dict[str, Path]:
    lookup = {}
    if not hwpx_dir.exists():
        return lookup
    for path in hwpx_dir.rglob("*.hwpx"):
        lookup[rfp.normalize_doc_name(path.name)] = path
    return lookup


def load_p3_sample_rows(project_root: Path, limit: int = 250) -> pd.DataFrame:
    p3_meta_path = project_root / "outputs" / f"parsing_p3_{limit}" / f"metadata_light_{limit}.xlsx"
    if not p3_meta_path.exists():
        raise FileNotFoundError(f"P3 sample metadata not found: {p3_meta_path}")
    sample_df = pd.read_excel(p3_meta_path).sort_values("rank_index").head(limit).copy()
    original_inventory = rfp.build_original_inventory(project_root / "data" / "original_data_list")
    by_source_file = {row["source_file"]: row for _, row in original_inventory.iterrows()}
    source_paths = []
    for _, row in sample_df.iterrows():
        source = by_source_file.get(row["source_file"])
        source_paths.append(source["source_path"] if source is not None else "")
    sample_df["source_path"] = source_paths
    sample_df["norm_name"] = sample_df["source_file"].map(rfp.normalize_doc_name)
    sample_df["doc_id"] = sample_df["source_file"].map(make_doc_id)
    sample_df["doc_key"] = sample_df["source_file"].map(make_doc_key)
    sample_df["pilot_doc_id"] = sample_df["doc_id"].map(lambda x: "D" + str(x).replace("doc_", "")[:10])
    return sample_df


def strip_project_prefixes(text: str) -> str:
    text = rfp.normalize_doc_name(text)
    text = re.sub(r"^\s*[\[\(【]?\s*(긴급|재공고|지문|국제|협상|전자입찰|수의계약)\s*[\]\)】]?\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\-_]+", "", text)
    return text.strip()


def project_aliases(source_file: str, project_name: str = "") -> list[str]:
    issuer, inferred_project = rfp.infer_doc_title_fields(source_file)
    candidates = [
        source_file,
        rfp.normalize_doc_name(source_file),
        project_name,
        inferred_project,
        strip_project_prefixes(project_name or inferred_project),
    ]
    aliases = []
    for value in candidates:
        value = normalize_space(value)
        if value and value not in aliases:
            aliases.append(value)
    compact = re.sub(r"[\s\[\]\(\)【】_\-]+", "", aliases[0]) if aliases else ""
    if compact and compact not in aliases:
        aliases.append(compact)
    return aliases[:6]


def normalize_date_policy_bid_deadline_only(date_summary: dict) -> dict:
    """P4 outputs retain only bid deadline among date fields."""
    cleaned = dict(date_summary or {})
    for key in ["final_published_at", "final_bid_start", "published_at_evidence", "bid_start_evidence"]:
        cleaned[key] = ""
    cleaned["published_at_status"] = "not_used"
    cleaned["bid_start_status"] = "not_used"
    return cleaned


def parse_g2b_bid_deadline(raw_value: str) -> str:
    """Extract only the parenthesized bid deadline from 게시일시(입찰마감일시)."""
    text = str(raw_value or "").strip()
    match = re.search(r"\(([^()]*)\)\s*$", text)
    if not match:
        return ""
    value = match.group(1).strip()
    if not value or value == "-":
        return ""
    date_match = re.match(
        r"(?P<year>\d{4})[./-](?P<month>\d{1,2})[./-](?P<day>\d{1,2})"
        r"(?:\s+(?P<hour>\d{1,2})[:시](?P<minute>\d{2})?)?",
        value,
    )
    if not date_match:
        return value
    year = int(date_match.group("year"))
    month = int(date_match.group("month"))
    day = int(date_match.group("day"))
    hour = date_match.group("hour")
    minute = date_match.group("minute") or "00"
    if hour is None:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return f"{year:04d}-{month:02d}-{day:02d} {int(hour):02d}:{int(minute):02d}"


def parse_notice_revision(notice_id: str) -> tuple[str, int]:
    text = str(notice_id or "").strip()
    match = re.match(r"^(?P<base>.+?)-(?P<revision>\d+)$", text)
    if not match:
        return text, 0
    try:
        revision = int(match.group("revision"))
    except Exception:
        revision = 0
    return match.group("base"), revision


def g2b_deadline_sort_value(row: dict) -> int:
    digits = re.sub(r"\D", "", str(row.get("bid_deadline", "")))
    return int(digits[:12] or 0)


def tokenize_match_text(text: str) -> set[str]:
    text = strip_project_prefixes(rfp.normalize_doc_name(text))
    tokens = {
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text)
        if token.strip()
    }
    stopwords = {"사업", "용역", "구축", "시스템", "정보", "개발", "고도화", "운영", "유지관리", "재공고", "긴급", "입찰공고"}
    return {token for token in tokens if token not in stopwords}


def is_cancelled_g2b_notice(kind: str) -> bool:
    return "취소" in str(kind or "")


def normalize_g2b_record(row: dict) -> dict:
    notice_id = normalize_space(row.get("입찰공고번호", ""))
    notice_base, notice_revision = parse_notice_revision(notice_id)
    kind = normalize_space(row.get("구분", ""))
    title = normalize_space(row.get("공고명", ""))
    notice_agency = normalize_space(row.get("공고기관", ""))
    demand_agency = normalize_space(row.get("수요기관", ""))
    bid_deadline = parse_g2b_bid_deadline(row.get("게시일시(입찰마감일시)", ""))
    return {
        "notice_id": notice_id,
        "notice_base": notice_base,
        "notice_revision": notice_revision,
        "kind": kind,
        "kind_priority": G2B_KIND_PRIORITY.get(kind, 0),
        "title": title,
        "notice_agency": notice_agency,
        "demand_agency": demand_agency,
        "bid_deadline": bid_deadline,
        "bid_deadline_source": "게시일시(입찰마감일시).parenthesized_bid_deadline",
        "is_cancelled": is_cancelled_g2b_notice(kind),
        "compact_title": compact_match_text(title),
        "title_tokens": tokenize_match_text(title),
        "compact_notice_agency": compact_match_text(notice_agency),
        "compact_demand_agency": compact_match_text(demand_agency),
    }


def load_g2b_records(project_root: Path) -> list[dict]:
    path = project_root / "data" / G2B_MASTER_FILENAME
    if not path.exists():
        return []
    df = pd.read_csv(path)
    required = {"입찰공고번호", "구분", "공고명", "공고기관", "수요기관", "게시일시(입찰마감일시)"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{G2B_MASTER_FILENAME} 필수 컬럼 누락: {missing}")
    return [normalize_g2b_record(row.to_dict()) for _, row in df.iterrows()]


def g2b_score_match(doc_meta: dict, record: dict) -> tuple[int, list[str]]:
    issuer = doc_meta.get("issuer", "")
    project_name = doc_meta.get("project_name", "")
    source_file = doc_meta.get("source_file", "")
    project_compact = compact_match_text(project_name or source_file)
    title_compact = record.get("compact_title", "")
    project_tokens = tokenize_match_text(project_name or source_file)
    title_tokens = record.get("title_tokens") or set()
    reasons = []
    score = 0

    if project_compact and title_compact:
        ratio = SequenceMatcher(None, project_compact, title_compact).ratio()
        score += int(ratio * 48)
        if project_compact in title_compact or title_compact in project_compact:
            score += 28
            reasons.append("title_containment")
        elif ratio >= 0.82:
            score += 10
            reasons.append("title_high_ratio")

    if project_tokens and title_tokens:
        overlap = project_tokens & title_tokens
        recall = len(overlap) / max(1, len(project_tokens))
        precision = len(overlap) / max(1, len(title_tokens))
        score += int(max(recall, precision) * 24)
        if len(overlap) >= 2:
            reasons.append("token_overlap")

    issuer_compact = compact_match_text(issuer)
    agency_compacts = [record.get("compact_notice_agency", ""), record.get("compact_demand_agency", "")]
    if issuer_compact and any(issuer_compact and (issuer_compact in agency or agency in issuer_compact) for agency in agency_compacts if agency):
        score += 18
        reasons.append("agency_match")
    elif issuer_compact:
        best_agency_ratio = max((SequenceMatcher(None, issuer_compact, agency).ratio() for agency in agency_compacts if agency), default=0)
        if best_agency_ratio >= 0.78:
            score += 8
            reasons.append("agency_similar")
        else:
            score -= 4
            reasons.append("agency_mismatch")

    source_text = f"{source_file} {project_name}"
    kind = record.get("kind", "")
    title = record.get("title", "")
    if "재공고" in source_text:
        score += 12 if ("재공고" in kind or "재공고" in title) else -8
        reasons.append("re_notice_hint")
    if "긴급" in source_text:
        score += 6 if ("긴급" in kind or "긴급" in title) else 0
        reasons.append("urgent_hint")
    if "감리" in title and "감리" not in source_text:
        score -= 18
        reasons.append("audit_title_penalty")

    doc_numbers = set(re.findall(r"\d{2,}", source_text))
    title_numbers = set(re.findall(r"\d{2,}", record.get("title", "")))
    if doc_numbers and title_numbers:
        number_overlap = doc_numbers & title_numbers
        if number_overlap:
            score += min(8, 3 * len(number_overlap))
            reasons.append("number_overlap")

    if record.get("is_cancelled"):
        reasons.append("cancelled")
    return max(0, score), reasons


def empty_g2b_match(status: str = "missing_g2b_master") -> dict:
    return {
        "status": status,
        "score": 0,
        "reason": "",
        "candidate_count": 0,
        "active_candidate_count": 0,
        "cancelled_candidate_count": 0,
        "conflict_status": "",
        "record": {},
        "cancelled_notice_ids": [],
        "ambiguous_notice_ids": [],
    }


def choose_g2b_match(doc_meta: dict, g2b_records: list[dict]) -> dict:
    if not g2b_records:
        return empty_g2b_match("missing_g2b_master")
    scored = []
    for record in g2b_records:
        score, reasons = g2b_score_match(doc_meta, record)
        if score >= G2B_MATCH_THRESHOLD - 18:
            scored.append({**record, "score": score, "score_reasons": reasons})
    scored.sort(
        key=lambda row: (
            -int(row.get("score", 0)),
            bool(row.get("is_cancelled")),
            -int(row.get("notice_revision", 0)),
            -int(row.get("kind_priority", 0)),
            -g2b_deadline_sort_value(row),
            row.get("notice_id", ""),
        )
    )
    active = [row for row in scored if not row.get("is_cancelled") and int(row.get("score", 0)) >= G2B_MATCH_THRESHOLD]
    cancelled = [row for row in scored if row.get("is_cancelled") and int(row.get("score", 0)) >= G2B_MATCH_THRESHOLD]
    result = empty_g2b_match("no_confident_match")
    result.update({
        "candidate_count": len(scored),
        "active_candidate_count": len(active),
        "cancelled_candidate_count": len(cancelled),
        "cancelled_notice_ids": [row.get("notice_id", "") for row in cancelled[:5] if row.get("notice_id")],
    })
    if active:
        active.sort(
            key=lambda row: (
                -int(row.get("score", 0)),
                -int(row.get("notice_revision", 0)),
                -int(row.get("kind_priority", 0)),
                -g2b_deadline_sort_value(row),
                row.get("notice_id", ""),
            )
        )
        top = active[0]
        close = [
            row for row in active[1:]
            if int(top.get("score", 0)) - int(row.get("score", 0)) <= G2B_AMBIGUOUS_MARGIN
            and row.get("notice_base") != top.get("notice_base")
        ]
        if close:
            return {
                **result,
                "status": "ambiguous_active",
                "score": int(top.get("score", 0)),
                "reason": ",".join(top.get("score_reasons", [])),
                "conflict_status": "multiple_close_active_notice_bases",
                "record": top,
                "ambiguous_notice_ids": [row.get("notice_id", "") for row in [top, *close[:4]] if row.get("notice_id")],
            }
        deadlines = {row.get("bid_deadline", "") for row in active if row.get("bid_deadline")}
        conflict_status = "multiple_active_deadlines" if len(deadlines) > 1 and len(active) > 1 else ""
        return {
            **result,
            "status": "matched_active",
            "score": int(top.get("score", 0)),
            "reason": ",".join(top.get("score_reasons", [])),
            "conflict_status": conflict_status,
            "record": top,
        }
    if cancelled:
        top = cancelled[0]
        return {
            **result,
            "status": "cancelled_only",
            "score": int(top.get("score", 0)),
            "reason": ",".join(top.get("score_reasons", [])),
            "conflict_status": "only_confident_match_is_cancelled",
            "record": top,
        }
    if scored:
        top = scored[0]
        result.update({
            "score": int(top.get("score", 0)),
            "reason": ",".join(top.get("score_reasons", [])),
            "record": top,
        })
    return result


def g2b_match_metadata(match: dict) -> dict:
    record = match.get("record") or {}
    if match.get("status") not in {"matched_active", "cancelled_only", "ambiguous_active"}:
        record = {}
    return {
        "g2b_match_status": match.get("status", ""),
        "g2b_match_score": match.get("score", 0),
        "g2b_match_reason": match.get("reason", ""),
        "g2b_candidate_count": match.get("candidate_count", 0),
        "g2b_active_candidate_count": match.get("active_candidate_count", 0),
        "g2b_cancelled_candidate_count": match.get("cancelled_candidate_count", 0),
        "g2b_conflict_status": match.get("conflict_status", ""),
        "g2b_notice_id": record.get("notice_id", ""),
        "g2b_notice_base": record.get("notice_base", ""),
        "g2b_notice_revision": record.get("notice_revision", ""),
        "g2b_notice_kind": record.get("kind", ""),
        "g2b_is_cancelled": bool(record.get("is_cancelled", False)),
        "g2b_title": record.get("title", ""),
        "g2b_notice_agency": record.get("notice_agency", ""),
        "g2b_demand_agency": record.get("demand_agency", ""),
        "g2b_bid_deadline": record.get("bid_deadline", ""),
        "g2b_bid_deadline_source": record.get("bid_deadline_source", ""),
        "g2b_cancelled_notice_ids": " | ".join(match.get("cancelled_notice_ids", [])),
        "g2b_ambiguous_notice_ids": " | ".join(match.get("ambiguous_notice_ids", [])),
    }


def apply_g2b_metadata(doc_meta: dict, match: dict, date_summary: dict) -> dict:
    metadata = g2b_match_metadata(match)
    doc_meta.update(metadata)
    if match.get("status") != "matched_active":
        return metadata

    record = match.get("record") or {}
    notice_id = record.get("notice_id", "")
    if notice_id:
        doc_meta["external_notice_id"] = notice_id
        doc_meta["notice_id"] = notice_id
        doc_meta["final_notice_id"] = notice_id
        doc_meta["notice_id_status"] = "g2b_matched"
        doc_meta["notice_id_evidence"] = f"G2B {record.get('kind', '')}: {record.get('title', '')}"

    bid_deadline = record.get("bid_deadline", "")
    if bid_deadline:
        doc_meta["bid_deadline"] = bid_deadline
        doc_meta["final_bid_deadline"] = bid_deadline
        doc_meta["bid_deadline_status"] = "g2b_matched"
        doc_meta["bid_deadline_evidence"] = f"G2B 입찰마감일시: {bid_deadline}"
        date_summary["final_bid_deadline"] = bid_deadline
        date_summary["bid_deadline_status"] = "g2b_matched"
        date_summary["bid_deadline_evidence"] = doc_meta["bid_deadline_evidence"]
    return metadata


def g2b_common_metadata(doc_meta: dict) -> dict:
    return {key: as_scalar(doc_meta.get(key, "")) for key in G2B_METADATA_KEYS}


def p4_block_common_metadata(doc_meta: dict) -> dict:
    metadata = rfp.block_common_metadata(doc_meta)
    metadata.update(g2b_common_metadata(doc_meta))
    return metadata


def refresh_p4_block_metadata(block: dict, doc_meta: dict) -> None:
    block.update(p4_block_common_metadata(doc_meta))


def source_feature_text(source: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    values = [source.get("source_file", ""), source.get("norm_name", "")]
    for col in ["사업명", "공고명", "사업 요약", "텍스트", "발주 기관", "발주기관", "사업 금액", "사업금액"]:
        value = meta.get(col)
        if value is not None and str(value).strip() and str(value).lower() != "nan":
            values.append(str(value))
    return "\n".join(values)[:30000]


def primary_business_type(*texts: str) -> str:
    types = infer_business_types(*texts)
    return types[0] if types else "기타"


def table_density_proxy_score(source_file: str, meta: dict | None = None) -> int:
    text = source_feature_text({"source_file": source_file, "norm_name": rfp.normalize_doc_name(source_file)}, meta)
    score = 0
    for keyword in ["표", "평가기준", "배점", "요구사항", "제출서류", "산출내역", "목록", "붙임", "별지"]:
        if keyword in text:
            score += 1
    return min(score, 5)


def hard_distractor_reason(source: dict, meta: dict | None, eval_issuers: set[str], eval_project_tokens: set[str]) -> str:
    issuer, project_name = rfp.infer_doc_title_fields(source.get("source_file", ""))
    feature_text = source_feature_text(source, meta)
    reasons = []
    if issuer and issuer in eval_issuers:
        reasons.append("same_issuer")
    if any(token and token in feature_text for token in eval_project_tokens):
        reasons.append("similar_project_token")
    if any(token in feature_text for token in ["재공고", "긴급", "정정공고", "취소공고"]):
        reasons.append("notice_variant")
    if strip_project_prefixes(project_name) != project_name:
        reasons.append("prefix_alias")
    return "+".join(reasons)


def build_filler_candidates(
    original_inventory_df: pd.DataFrame,
    metadata_lookup: dict[str, dict],
    selected_norms: set[str],
    eval_rows: list[dict],
) -> list[dict]:
    eval_issuers = {rfp.infer_doc_title_fields(row.get("source_file", ""))[0] for row in eval_rows}
    eval_issuers.discard("")
    eval_project_tokens = set()
    for row in eval_rows:
        _, project_name = rfp.infer_doc_title_fields(row.get("source_file", ""))
        stripped = strip_project_prefixes(project_name)
        for token in re.split(r"[\s_\-()\[\]【】]+", stripped):
            if len(token) >= 4 and not re.fullmatch(r"\d+", token):
                eval_project_tokens.add(token)
    candidates = []
    preferred_sources = {}
    for _, source_row in original_inventory_df.iterrows():
        source = source_row.to_dict()
        norm = source["norm_name"]
        current = preferred_sources.get(norm)
        priority = {"hwp": 0, "hwpx": 0, "pdf": 2}.get(str(source.get("file_type", "")).lower(), 9)
        current_priority = {"hwp": 0, "hwpx": 0, "pdf": 2}.get(str((current or {}).get("file_type", "")).lower(), 9)
        if current is None or (priority, source["source_file"]) < (current_priority, current["source_file"]):
            preferred_sources[norm] = source

    for source in preferred_sources.values():
        norm = source["norm_name"]
        if norm in selected_norms:
            continue
        meta = metadata_lookup.get(norm, {})
        score, reason = rfp.score_sampling_candidate(source["source_file"], meta)
        feature_text = source_feature_text(source, meta)
        business_type = primary_business_type(source["source_file"], feature_text)
        table_score = table_density_proxy_score(source["source_file"], meta)
        hard_reason = hard_distractor_reason(source, meta, eval_issuers, eval_project_tokens)
        signal_bonus = sum(1 for keyword in [
            "사업금액", "사업비", "예산", "제출서류", "제출방법", "제출장소",
            "입찰참가자격", "자격요건", "평가기준", "배점", "사업기간",
        ] if keyword in feature_text)
        final_score = int(score) + table_score * 3 + signal_bonus * 2 + (12 if hard_reason else 0)
        issuer, project_name = rfp.infer_doc_title_fields(source["source_file"])
        candidates.append({
            **source,
            "is_eval_ground_truth": False,
            "sampling_reason": reason,
            "sample_score": final_score,
            "base_sample_score": int(score),
            "eval_question_count": 0,
            "selection_bucket": business_type,
            "table_density_proxy": table_score,
            "hard_distractor": bool(hard_reason),
            "hard_distractor_reason": hard_reason,
            "issuer": issuer,
            "project_name": project_name,
            "business_type_candidates": ", ".join(infer_business_types(source["source_file"], feature_text)),
            **rfp.db_metadata_fields_from_source(source),
        })
    return candidates


def select_balanced_fillers(candidates: list[dict], filler_count: int) -> list[dict]:
    sorted_candidates = sorted(
        candidates,
        key=lambda r: (
            not bool(r.get("hard_distractor")),
            -int(r.get("sample_score", 0)),
            {"hwp": 0, "hwpx": 1, "pdf": 2}.get(str(r.get("file_type", "")).lower(), 9),
            r.get("source_file", ""),
        ),
    )
    selected = []
    selected_norms = set()
    issuer_counts = Counter()

    def add(row: dict, max_per_issuer: int | None = None) -> bool:
        norm = row.get("norm_name", "")
        if norm in selected_norms:
            return False
        issuer = row.get("issuer", "")
        if max_per_issuer is not None and issuer and issuer_counts[issuer] >= max_per_issuer:
            return False
        selected.append(row)
        selected_norms.add(norm)
        if issuer:
            issuer_counts[issuer] += 1
        return True

    hard_limit = min(P4_125_HARD_DISTRACTOR_TARGET, filler_count)
    for row in sorted_candidates:
        if len(selected) >= hard_limit:
            break
        if row.get("hard_distractor"):
            add(row, max_per_issuer=4)

    by_bucket = defaultdict(list)
    for row in sorted_candidates:
        if row.get("norm_name") in selected_norms:
            continue
        by_bucket[row.get("selection_bucket") or "기타"].append(row)
    for bucket in by_bucket:
        by_bucket[bucket].sort(key=lambda r: (-int(r.get("sample_score", 0)), r.get("source_file", "")))

    while len(selected) < filler_count:
        added_this_round = False
        for bucket in BUSINESS_TYPE_BUCKETS:
            bucket_rows = by_bucket.get(bucket) or []
            while bucket_rows:
                row = bucket_rows.pop(0)
                if add(row, max_per_issuer=3):
                    added_this_round = True
                    break
            if len(selected) >= filler_count:
                break
        if not added_this_round:
            break

    if len(selected) < filler_count:
        for row in sorted_candidates:
            if len(selected) >= filler_count:
                break
            add(row, max_per_issuer=None)
    return selected[:filler_count]


def build_eval_covered_125_sample_rows(project_root: Path, output_dir: Path | None = None) -> tuple[pd.DataFrame, dict]:
    eval_docs_df = rfp.load_eval_ground_truth_docs(project_root / "data" / "eval")
    original_inventory_df = rfp.build_original_inventory(project_root / "data" / "original_data_list")
    metadata_df = rfp.load_metadata(
        project_root / "data" / "data_list_advanced.xlsx",
        project_root / "data" / "data_list_reparsed.xlsx",
    )
    metadata_lookup = rfp.build_metadata_lookup(metadata_df)
    if eval_docs_df.empty:
        raise FileNotFoundError("eval ground_truth_docs를 찾지 못했습니다: data/eval/*.csv")
    if original_inventory_df.empty:
        raise FileNotFoundError("원본 RFP 파일을 찾지 못했습니다: data/original_data_list")

    original_by_norm = defaultdict(list)
    for _, row in original_inventory_df.iterrows():
        original_by_norm[row["norm_name"]].append(row.to_dict())

    selected_rows = []
    selected_norms = set()
    missing_eval_docs = []
    for _, eval_row in eval_docs_df.iterrows():
        norm = eval_row["norm_name"]
        matches = original_by_norm.get(norm, [])
        if not matches:
            missing_eval_docs.append(norm)
            continue
        matches = sorted(matches, key=lambda r: ({"hwp": 0, "hwpx": 1, "pdf": 2}.get(r["file_type"], 9), r["source_file"]))
        source = matches[0]
        meta = metadata_lookup.get(norm, {})
        score, reason = rfp.score_sampling_candidate(source["source_file"], meta)
        issuer, project_name = rfp.infer_doc_title_fields(source["source_file"])
        feature_text = source_feature_text(source, meta)
        selected_norms.add(norm)
        selected_rows.append({
            **source,
            "is_eval_ground_truth": True,
            "sampling_reason": "eval_ground_truth",
            "sample_score": int(score),
            "base_sample_score": int(score),
            "eval_question_count": int(eval_row["question_count"]),
            "selection_bucket": primary_business_type(source["source_file"], feature_text),
            "table_density_proxy": table_density_proxy_score(source["source_file"], meta),
            "hard_distractor": False,
            "hard_distractor_reason": "",
            "issuer": issuer,
            "project_name": project_name,
            "business_type_candidates": ", ".join(infer_business_types(source["source_file"], feature_text)),
            "eval_files": eval_row.get("eval_files", ""),
            "eval_raw_examples": eval_row.get("raw_examples", ""),
            **rfp.db_metadata_fields_from_source(source),
        })

    if missing_eval_docs:
        raise FileNotFoundError("원본에서 매칭되지 않은 eval 문서가 있습니다: " + " | ".join(missing_eval_docs))

    filler_needed = P4_125_TARGET_DOCS - len(selected_rows)
    if filler_needed < 0:
        raise RuntimeError(f"eval 문서 수가 target {P4_125_TARGET_DOCS}개보다 많습니다: {len(selected_rows)}")
    filler_candidates = build_filler_candidates(original_inventory_df, metadata_lookup, selected_norms, selected_rows)
    filler_rows = select_balanced_fillers(filler_candidates, filler_needed)
    if len(filler_rows) != filler_needed:
        raise RuntimeError(f"125 corpus filler가 {filler_needed}개 필요하지만 {len(filler_rows)}개만 선택됐습니다.")

    selected_rows.extend(filler_rows)
    pilot = pd.DataFrame(selected_rows).reset_index(drop=True)
    pilot.insert(0, "pilot_index", range(1, len(pilot) + 1))
    pilot["rank_index"] = pilot["pilot_index"]
    pilot["doc_id"] = pilot["source_file"].map(make_doc_id)
    pilot["doc_key"] = pilot["source_file"].map(make_doc_key)
    pilot["pilot_doc_id"] = pilot["doc_id"].map(lambda x: "D" + str(x).replace("doc_", "")[:10])
    pilot["selection_aliases"] = [
        " | ".join(project_aliases(row.source_file, getattr(row, "project_name", "")))
        for row in pilot.itertuples(index=False)
    ]

    eval_included = int(pilot["is_eval_ground_truth"].astype(bool).sum())
    hard_count = int(pilot["hard_distractor"].astype(bool).sum())
    selection_report = {
        "selection_rule": "eval-covered-125: include every physical source document matched from deduplicated data/eval batch 01~25 ground_truth_docs, then add balanced signal-rich and hard-distractor fillers",
        "document_count": int(len(pilot)),
        "eval_physical_source_docs_included": eval_included,
        "additional_sampled_docs": int((~pilot["is_eval_ground_truth"].astype(bool)).sum()),
        "missing_eval_gt_docs": [],
        "actual_eval_unique_gt_docs": int(len(eval_docs_df)),
        "expected_eval_physical_source_docs": int(len(eval_docs_df)),
        "planned_additional_sampled_docs": int(filler_needed),
        "actual_additional_sampled_docs": int(filler_needed),
        "eval_count_matches_plan": bool(eval_included == len(eval_docs_df)),
        "filler_criteria": [
            "사업유형 bucket round-robin",
            "발주기관 과집중 제한 후 부족 시 완화",
            "file type 우선순위 hwp/hwpx/pdf",
            "table density proxy",
            "budget/submission/eligibility/evaluation signal score",
            "same issuer/similar project/reannouncement hard distractor boost",
        ],
        "hard_distractor_target": P4_125_HARD_DISTRACTOR_TARGET,
        "hard_distractor_count": hard_count,
        "business_type_bucket_counts": pilot["selection_bucket"].value_counts(dropna=False).to_dict(),
        "file_type_counts": pilot["file_type"].value_counts(dropna=False).to_dict(),
        "parser_version": PARSER_VERSION,
    }

    if len(pilot) != P4_125_TARGET_DOCS:
        raise AssertionError(f"pilot 문서 수가 {P4_125_TARGET_DOCS}개가 아닙니다: {len(pilot)}")
    if eval_included != len(eval_docs_df):
        raise AssertionError(f"eval physical source doc 수가 eval CSV unique doc 수와 다릅니다: expected={len(eval_docs_df)} actual={eval_included}")
    if pilot["norm_name"].nunique() != len(pilot):
        duplicates = pilot.loc[pilot["norm_name"].duplicated(keep=False), "norm_name"].tolist()
        raise AssertionError("pilot 문서 norm_name 중복이 있습니다: " + " | ".join(duplicates[:20]))

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        pilot.to_csv(output_dir / "pilot_docs_125.csv", index=False, encoding="utf-8-sig")
    return pilot, selection_report


def load_sample_rows(project_root: Path, limit: int, output_dir: Path) -> tuple[pd.DataFrame, dict]:
    if int(limit) == P4_125_LIMIT:
        return build_eval_covered_125_sample_rows(project_root, output_dir)
    return load_p3_sample_rows(project_root, limit=limit), {
        "selection_rule": f"reuse P3 metadata sample outputs/parsing_p3_{limit}/metadata_light_{limit}.xlsx",
        "sample_source": f"outputs/parsing_p3_{limit}/metadata_light_{limit}.xlsx",
        "parser_version": PARSER_VERSION,
    }


def choose_parse_source(doc_row: dict, project_root: Path, hwpx_lookup: dict[str, Path]) -> tuple[Path, str]:
    source_file = str(doc_row.get("source_file", ""))
    norm = rfp.normalize_doc_name(source_file)
    file_type = str(doc_row.get("file_type", "")).lower()
    if file_type == "hwp" and norm in hwpx_lookup:
        return hwpx_lookup[norm], "hwpx"
    source_path = Path(str(doc_row.get("source_path", "")))
    if file_type == "hwpx":
        return source_path, "hwpx"
    if file_type == "pdf":
        return source_path, "pdf"
    return source_path, "hwp_fallback"


def prepare_doc_meta(doc_row: dict, parse_path: Path, source_format: str) -> dict:
    doc_meta = rfp.sanitize_doc_meta_for_db(doc_row)
    doc_meta["doc_id"] = make_doc_id(doc_meta.get("source_file", ""))
    doc_meta["doc_key"] = make_doc_key(doc_meta.get("source_file", ""))
    doc_meta["pilot_doc_id"] = "D" + doc_meta["doc_id"].replace("doc_", "")[:10]
    doc_meta["norm_name"] = rfp.normalize_doc_name(doc_meta.get("source_file", ""))
    doc_meta["source_format"] = source_format
    doc_meta["parse_path"] = str(parse_path)
    return doc_meta


def make_light_context_header(block: dict) -> str:
    section = section_to_text(block.get("section_path"))
    parts = [
        f"문서: {block.get('source_file')}",
        f"사업명: {block.get('project_name') or 'unknown'}",
        f"발주기관: {block.get('issuer') or 'unknown'}",
        f"섹션: {section or '없음'}",
        f"유형: {block.get('block_type')}",
    ]
    return "[" + " | ".join(parts) + "]"


def block_sequence_token(block: dict) -> str:
    raw = str(block.get("block_id") or "block")
    match = re.search(r"_(toc|text|table|fact)_(\d{4})", raw)
    return f"{match.group(1)}_{match.group(2)}" if match else safe_filename_token(raw, 40)


def blocks_to_retrieval_records(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    chunks, source_records = [], []
    for block in blocks:
        block_type = block.get("block_type", "text")
        text = f"{make_light_context_header(block)}\n{block.get('text', '')}".strip()
        if not text:
            continue
        block_hash = sha1_short(text, 12)
        block_token = block_sequence_token(block)
        doc_id = block["doc_id"]
        chunk_type = "fact_candidates" if block_type == "fact_candidates" else block_type
        source_store_id = f"src_{doc_id}_{chunk_type}_{block_token}_{block_hash}"
        fact_confidence = block.get("fact_confidence", "")
        fact_status = block.get("fact_status", "")
        source_record = {
            "source_store_id": source_store_id,
            "doc_id": doc_id,
            "doc_key": block.get("doc_key") or make_doc_key(block.get("source_file", "")),
            "source_file": block.get("source_file", ""),
            "source_format": block.get("source_format", ""),
            "source_type": chunk_type,
            "full_text": text,
            "section_path": section_to_text(block.get("section_path")),
            "block_id": block.get("block_id", ""),
            "content_hash": block_hash,
        }
        for key in P4_SOURCE_AUDIT_METADATA_KEYS:
            source_record[key] = as_scalar(block.get(key, ""))
        if chunk_type == "table":
            source_record["table_structure"] = block.get("structured_data", {})
        source_records.append(source_record)
        for part_index, content in enumerate(rfp.split_text_with_overlap(text, max_chars=CHUNK_MAX_CHARS, overlap=CHUNK_OVERLAP), start=1):
            content = content.strip()
            if not content:
                continue
            content_hash = sha1_short(content, 12)
            chunk_id = f"{doc_id}_{chunk_type}_{block_token}_part_{part_index:03d}_{content_hash}"
            embed_enabled = bool(block.get("embed_enabled", block_type != "toc"))
            if block_type == "fact_candidates" and (fact_confidence == "low" or fact_status == "needs_review"):
                embed_enabled = False
            metadata = {
                "doc_id": doc_id,
                "doc_key": block.get("doc_key") or make_doc_key(block.get("source_file", "")),
                "source_file": block.get("source_file", ""),
                "source_format": block.get("source_format", ""),
                "file_type": block.get("file_type", ""),
                "chunk_type": chunk_type,
                "section_path": section_to_text(block.get("section_path")),
                "section_type": block.get("section_type", ""),
                "issuer": block.get("issuer", ""),
                "project_name": block.get("project_name", ""),
            }
            for key in P4_RETRIEVAL_METADATA_KEYS:
                value = as_scalar(block.get(key, ""))
                if key == "g2b_match_status" and value == "no_confident_match":
                    continue
                if value:
                    metadata[key] = value
            if chunk_type == "fact_candidates":
                metadata.update({"fact_type": block.get("fact_type", ""), "fact_status": fact_status, "fact_confidence": fact_confidence})
            if chunk_type == "table":
                metadata.update({
                    "table_role": block.get("table_role", ""),
                    "table_signal_score": block.get("table_signal_score", 0),
                    "table_embed_reason": block.get("table_embed_reason", ""),
                })
            chunk = {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "doc_key": metadata["doc_key"],
                "source_file": block.get("source_file", ""),
                "source_format": block.get("source_format", ""),
                "chunk_type": chunk_type,
                "embed_enabled": bool(embed_enabled),
                "content": content,
                "metadata": {k: as_scalar(v) for k, v in metadata.items()},
                "source_ref": {
                    "source_store_id": source_store_id,
                    "block_id": block.get("block_id", ""),
                    "part_index": part_index,
                    "content_hash": content_hash,
                },
            }
            if chunk_type == "fact_candidates":
                chunk.update({
                    "fact_type": block.get("fact_type", ""),
                    "fact_status": fact_status,
                    "fact_confidence": fact_confidence,
                    "evidence_text_short": block.get("evidence_text_short", ""),
                })
            chunks.append(chunk)
    return chunks, source_records


def infer_business_types(*texts: str) -> list[str]:
    joined = " ".join(str(t or "") for t in texts)
    rules = [
        ("유지관리", ["유지관리", "운영유지", "유지 보수", "유지보수"]),
        ("고도화", ["고도화", "기능개선", "개선"]),
        ("구축", ["구축", "개발", "신규"]),
        ("운영", ["운영", "위탁운영"]),
        ("데이터/AI", ["데이터", "AI", "인공지능", "빅데이터"]),
        ("보안", ["보안", "정보보호", "개인정보"]),
        ("클라우드", ["클라우드", "SaaS", "IaaS", "PaaS"]),
        ("홈페이지/포털", ["홈페이지", "포털", "웹사이트", "누리집"]),
        ("컨설팅/감리", ["컨설팅", "감리", "진단", "ISP", "ISMP"]),
    ]
    return [label for label, keywords in rules if any(k in joined for k in keywords)][:4]


def extract_submission_logistics(clean_text: str) -> dict:
    lines = rfp.clean_lines(clean_text)
    candidate_lines = []
    for line in lines:
        if len(line) > 280:
            continue
        if not any(k in line for k in ["제안서", "입찰서", "서류", "제출"]):
            continue
        if any(k in line for k in ["일시", "기한", "마감", "장소", "방법", "온라인", "나라장터", "e-발주시스템", "방문", "우편", "제출장소", "제출처"]):
            candidate_lines.append(line)
        if len(candidate_lines) >= 12:
            break
    method_terms = [term for term in ["나라장터", "e-발주시스템", "온라인", "방문", "우편", "직접 제출", "전자 제출"] if any(term in line for line in candidate_lines)]
    date_lines = [line for line in candidate_lines if any(k in line for k in ["일시", "기한", "마감", "까지", "제출기간"])]
    place_lines = [line for line in candidate_lines if any(k in line for k in ["장소", "제출처", "주소", "방문"])]
    return {
        "submission_logistics_lines": candidate_lines,
        "proposal_submission_date_hint": truncate(" | ".join(date_lines[:3]), 260),
        "proposal_submission_method_hint": " | ".join(method_terms[:5]),
        "proposal_submission_place_hint": truncate(" | ".join(place_lines[:3]), 260),
    }


def collect_eligibility_terms(items: list[dict], limit: int = 20) -> list[str]:
    terms = []
    for item in items[:12]:
        for term in item.get("matched_terms") or []:
            if term and term not in terms:
                terms.append(term)
        raw = normalize_space(item.get("raw_text", ""))
        if raw and len(raw) <= 120 and raw not in terms:
            terms.append(raw)
        if len(terms) >= limit:
            break
    return terms[:limit]


def make_fact_block(
    doc_meta: dict,
    fact_seq: int,
    fact_type: str,
    parts: list[str],
    evidence: list[str] | None = None,
    confidence: str = "high",
    status: str = "extracted",
) -> dict | None:
    parts = [normalize_space(part) for part in parts if normalize_space(part)]
    if not parts:
        return None
    alias = FACT_TYPE_ALIASES.get(fact_type, fact_type)
    text = f"{alias}: " + " | ".join(parts)
    evidence = evidence or []
    return {
        "parser_version": PARSER_VERSION,
        "pilot_doc_id": doc_meta["pilot_doc_id"],
        "doc_id": doc_meta["doc_id"],
        "doc_key": doc_meta["doc_key"],
        "norm_name": doc_meta["norm_name"],
        "source_file": doc_meta["source_file"],
        "source_format": doc_meta.get("source_format", ""),
        "file_type": doc_meta.get("file_type", ""),
        **p4_block_common_metadata(doc_meta),
        "block_id": f"{doc_meta['pilot_doc_id']}_v2_fact_{fact_seq:04d}_{fact_type}",
        "block_type": "fact_candidates",
        "section_path": ["핵심 후보 정보", fact_type],
        "section_type": "핵심 후보 정보",
        "text": text,
        "structured_data": {
            "fact_type": fact_type,
            "aliases": alias,
            "parts": parts[:12],
        },
        "exact_terms": rfp.extract_exact_terms(text, doc_meta),
        "dates": rfp.extract_dates(text),
        "amounts": rfp.extract_amount_strings(text),
        "char_len": len(text),
        "fact_type": fact_type,
        "fact_status": status,
        "fact_confidence": confidence,
        "evidence_text_short": truncate(" / ".join(str(x) for x in evidence if x), 500),
    }


def build_compact_fact_blocks(doc_meta: dict, clean_text: str, summaries: dict) -> list[dict]:
    blocks = []
    seq = 1
    budget = summaries.get("budget_summary", {})
    period = summaries.get("period_summary", {})
    dates = summaries.get("date_summary", {})
    logistics = summaries.get("submission_logistics", {})
    submission_names = summaries.get("final_submission_document_names", [])
    eligibility_terms = collect_eligibility_terms(summaries.get("final_eligibility_items", []))
    business_types = infer_business_types(doc_meta.get("project_name", ""), clean_text[:4000])
    aliases = project_aliases(doc_meta.get("source_file", ""), doc_meta.get("project_name", ""))

    summary_parts = [
        f"원본문서: {doc_meta.get('source_file', '')}",
        f"정규화 문서명: {doc_meta.get('norm_name', '')}",
        f"사업명: {doc_meta.get('project_name', '')}",
        "사업명 alias: " + " / ".join(aliases),
        f"발주기관: {doc_meta.get('issuer', '')}",
    ]
    if business_types:
        summary_parts.append("사업유형: " + ", ".join(business_types))
    if budget.get("final_budget"):
        summary_parts.append(f"사업금액: {budget.get('final_budget')}")
    if period.get("final_project_duration"):
        summary_parts.append(f"사업기간: {period.get('final_project_duration')}")
    if dates.get("final_bid_deadline"):
        summary_parts.append(f"입찰마감일: {dates.get('final_bid_deadline')}")
    if submission_names:
        summary_parts.append("핵심 제출서류: " + ", ".join(submission_names[:8]))
    if eligibility_terms:
        summary_parts.append("핵심 자격 신호: " + ", ".join(eligibility_terms[:8]))
    summary_confidence = "high" if len(summary_parts) >= 7 else "medium"
    block = make_fact_block(doc_meta, seq, "document_summary", summary_parts, confidence=summary_confidence)
    if block:
        blocks.append(block)
        seq += 1

    if budget.get("final_budget") and budget.get("final_budget_status") == "extracted":
        block = make_fact_block(
            doc_meta,
            seq,
            "budget",
            [f"사업금액: {budget.get('final_budget')}", f"KRW: {budget.get('final_budget_krw', '')}"],
            [budget.get("final_budget_evidence", "")],
            confidence="high",
        )
        if block:
            blocks.append(block)
            seq += 1
    elif budget.get("final_budget"):
        block = make_fact_block(
            doc_meta,
            seq,
            "budget",
            [f"사업금액 후보: {budget.get('final_budget')}"],
            [budget.get("final_budget_evidence", "")],
            confidence="low",
            status="needs_review",
        )
        if block:
            blocks.append(block)
            seq += 1

    duration_parts = []
    duration_evidence = []
    if period.get("final_project_duration"):
        duration_parts.append(f"사업기간: {period.get('final_project_duration')}")
        duration_evidence.append(period.get("final_project_duration_evidence", ""))
    if period.get("final_maintenance_period"):
        duration_parts.append(f"무상유지보수기간: {period.get('final_maintenance_period')}")
    if period.get("final_warranty_period"):
        duration_parts.append(f"하자담보책임기간: {period.get('final_warranty_period')}")
    block = make_fact_block(doc_meta, seq, "duration", duration_parts, duration_evidence, confidence="high" if duration_parts else "low")
    if block:
        blocks.append(block)
        seq += 1

    block = make_fact_block(
        doc_meta,
        seq,
        "bid_deadline",
        [f"입찰마감일: {dates.get('final_bid_deadline')}"] if dates.get("final_bid_deadline") else [],
        [dates.get("bid_deadline_evidence", "")],
        confidence="high",
    )
    if block:
        blocks.append(block)
        seq += 1

    block = make_fact_block(
        doc_meta,
        seq,
        "submission_documents",
        ["제출서류: " + ", ".join(submission_names[:25])] if submission_names else [],
        confidence="high" if len(submission_names) >= 2 else "medium",
    )
    if block:
        blocks.append(block)
        seq += 1

    logistics_parts = []
    if logistics.get("proposal_submission_date_hint"):
        logistics_parts.append("제안서 제출일자 후보: " + logistics["proposal_submission_date_hint"])
    if logistics.get("proposal_submission_method_hint"):
        logistics_parts.append("제출방법 후보: " + logistics["proposal_submission_method_hint"])
    if logistics.get("proposal_submission_place_hint"):
        logistics_parts.append("제출장소 후보: " + logistics["proposal_submission_place_hint"])
    block = make_fact_block(
        doc_meta,
        seq,
        "submission_logistics",
        logistics_parts,
        confidence="high" if len(logistics_parts) >= 2 else "medium",
    )
    if block:
        blocks.append(block)
        seq += 1

    block = make_fact_block(
        doc_meta,
        seq,
        "eligibility",
        ["입찰참가자격 키워드: " + ", ".join(eligibility_terms[:20])] if eligibility_terms else [],
        confidence="high" if len(eligibility_terms) >= 2 else "medium",
    )
    if block:
        blocks.append(block)
        seq += 1

    block = make_fact_block(
        doc_meta,
        seq,
        "business_type",
        ["사업유형 후보: " + ", ".join(business_types)] if business_types else [],
        confidence="medium",
    )
    if block:
        blocks.append(block)

    return blocks


def build_compact_fact_block(doc_meta: dict, clean_text: str, summaries: dict) -> dict | None:
    """Backward-compatible single-block wrapper for older notebooks."""
    blocks = build_compact_fact_blocks(doc_meta, clean_text, summaries)
    return blocks[0] if blocks else None


def table_blank_ratio(table: dict) -> float:
    cells = []
    for row in table.get("rows") or []:
        cells.extend(row.get("cells") or [])
    if not cells:
        return 1.0
    blanks = sum(1 for cell in cells if not normalize_space(cell.get("text", "")))
    return blanks / max(1, len(cells))


def classify_table_for_embedding(table: dict, text_for_embedding: str) -> tuple[str, int, bool, str]:
    text = normalize_space(text_for_embedding)
    section = section_to_text(table.get("section_path"))
    columns = " ".join(table.get("columns_candidate") or [])
    joined = f"{section} {columns} {text}"
    signal_score = sum(1 for keyword in HIGH_SIGNAL_TABLE_KEYWORDS if keyword in joined)
    low_signal_score = sum(1 for keyword in LOW_SIGNAL_TABLE_KEYWORDS if keyword in joined)
    shape = table.get("table_shape") or {}
    row_count = int(shape.get("row_count") or 0)
    col_count = int(shape.get("col_count") or 0)
    blank_ratio = table_blank_ratio(table)

    if signal_score >= 1:
        return "retrieval_signal", signal_score, True, "high_signal_keywords"
    if low_signal_score >= 1 and signal_score == 0:
        return "layout_or_toc", signal_score, False, "low_signal_layout_or_toc"
    if row_count <= 1 or col_count <= 1 or blank_ratio >= 0.72:
        return "weak_table", signal_score, False, "sparse_or_mostly_empty"
    if len(text) < 120 and signal_score == 0:
        return "weak_table", signal_score, False, "short_low_signal"
    return "generic_table", signal_score, True, "generic_table_kept"


def build_hwpx_table_blocks(doc_meta: dict, tables: list[dict]) -> list[dict]:
    blocks = []
    for table in tables:
        block_seq = int(table.get("table_seq", len(blocks) + 1))
        text_for_embedding = table.get("body_text", "")
        if not text_for_embedding.strip():
            continue
        table_role, table_signal_score, embed_enabled, table_embed_reason = classify_table_for_embedding(table, text_for_embedding)
        blocks.append({
            "parser_version": PARSER_VERSION,
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "doc_key": doc_meta["doc_key"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "source_format": doc_meta.get("source_format", ""),
            "file_type": doc_meta.get("file_type", ""),
            **p4_block_common_metadata(doc_meta),
            "block_id": f"{doc_meta['pilot_doc_id']}_v2_table_{block_seq:04d}",
            "block_type": "table",
            "section_path": list(table.get("section_path") or ["문서 시작"]),
            "section_type": rfp.classify_section(text_for_embedding),
            "text": text_for_embedding,
            "embed_enabled": embed_enabled,
            "table_role": table_role,
            "table_signal_score": table_signal_score,
            "table_embed_reason": table_embed_reason,
            "structured_data": {
                "table_shape": table.get("table_shape", {}),
                "columns_candidate": table.get("columns_candidate", []),
                "table_role": table_role,
                "table_signal_score": table_signal_score,
                "table_embed_reason": table_embed_reason,
                "rows": table.get("rows", []),
            },
            "exact_terms": rfp.extract_exact_terms(text_for_embedding, doc_meta),
            "dates": rfp.extract_dates(text_for_embedding),
            "amounts": rfp.extract_amount_strings(text_for_embedding),
            "char_len": len(text_for_embedding),
        })
    return blocks


def extract_structured_or_fallback(parse_path: Path, source_format: str) -> dict:
    if source_format == "hwpx":
        return extract_hwpx_structured(parse_path)
    extracted = rfp.extract_document_text(parse_path)
    extracted["non_table_clean_text"] = extracted.get("clean_text", "")
    extracted["tables"] = []
    extracted["table_count"] = 0
    extracted["image_count"] = 0
    return extracted


def build_doc_artifacts(
    doc_row: dict,
    project_root: Path,
    hwpx_lookup: dict[str, Path],
    g2b_records: list[dict] | None = None,
) -> dict:
    parse_path, source_format = choose_parse_source(doc_row, project_root, hwpx_lookup)
    doc_meta = prepare_doc_meta(doc_row, parse_path, source_format)
    started = time.time()
    extracted = extract_structured_or_fallback(parse_path, source_format)
    doc_summary = {
        "rank_index": int(doc_row.get("rank_index", 0)),
        "doc_id": doc_meta["doc_id"],
        "doc_key": doc_meta["doc_key"],
        "norm_name": doc_meta["norm_name"],
        "source_file": doc_meta["source_file"],
        "source_format": source_format,
        "parse_path": str(parse_path),
        "file_type": doc_meta.get("file_type", ""),
        "is_eval_ground_truth": bool(doc_row.get("is_eval_ground_truth", False)),
        "parser_status": extracted.get("parser_status", "failed"),
        "parser": extracted.get("parser", ""),
        "raw_char_len": extracted.get("raw_char_len", 0),
        "clean_char_len": extracted.get("clean_char_len", 0),
        "non_table_clean_char_len": extracted.get("non_table_clean_char_len", extracted.get("clean_char_len", 0)),
        "table_count": extracted.get("table_count", 0),
        "image_count": extracted.get("image_count", 0),
        "parse_seconds": round(time.time() - started, 3),
        "error": extracted.get("error", ""),
        "project_name": doc_meta.get("project_name", ""),
        "issuer": doc_meta.get("issuer", ""),
        "final_budget": "",
        "final_budget_krw": "",
        "final_budget_status": "missing",
        "final_project_duration": "",
        "final_notice_id": "",
        "notice_id_status": "missing",
        "final_bid_deadline": "",
        "bid_deadline_status": "missing",
        "final_submission_documents": "",
        "final_bid_eligibility_terms": "",
        "business_type_candidates": "",
        "chunk_count_v1": 0,
        "chunk_count_v2": 0,
        "source_store_count_v1": 0,
        "source_store_count_v2": 0,
        "fact_status": "",
        "fact_confidence": "",
        "fact_block_count": 0,
        "embedded_table_block_count": 0,
        "suppressed_table_block_count": 0,
        "text_preview_5000": "",
    }
    for key in G2B_METADATA_KEYS:
        doc_summary[key] = ""
    if extracted.get("parser_status") != "success" or not extracted.get("clean_text", "").strip():
        return {"summary": doc_summary, "chunks_v1": [], "source_store_v1": [], "chunks_v2": [], "source_store_v2": []}
    clean_text = extracted["clean_text"]
    non_table_clean_text = extracted.get("non_table_clean_text") or clean_text
    doc_summary["text_preview_5000"] = clean_text[:5000]
    notice_summary = rfp.extract_notice_id_summary(clean_text, doc_meta)
    doc_meta.update({
        "notice_id": notice_summary.get("final_notice_id", ""),
        "final_notice_id": notice_summary.get("final_notice_id", ""),
        "notice_id_status": notice_summary.get("notice_id_status", ""),
        "notice_id_evidence": notice_summary.get("notice_id_evidence", ""),
    })
    budget_candidates = rfp.extract_budget_candidates(clean_text, doc_meta)
    budget_summary = rfp.select_final_budget(budget_candidates)
    date_candidates = rfp.extract_date_candidates(clean_text, doc_meta)
    date_summary = normalize_date_policy_bid_deadline_only(rfp.select_final_dates(date_candidates))
    period_candidates = rfp.extract_period_candidates(clean_text, doc_meta)
    period_summary = rfp.select_final_periods(period_candidates)
    eligibility_candidates = rfp.extract_eligibility_candidates(clean_text, doc_meta)
    final_eligibility_items = rfp.select_final_eligibility_terms(eligibility_candidates)
    submission_candidates = rfp.extract_submission_doc_candidates(clean_text, doc_meta)
    final_submission_documents = rfp.select_final_submission_documents(submission_candidates)
    final_submission_document_names = rfp.flatten_final_submission_document_names(final_submission_documents)
    submission_logistics = extract_submission_logistics(clean_text)
    doc_meta.update(budget_summary)
    doc_meta.update(date_summary)
    doc_meta.update(period_summary)
    doc_meta["final_bid_eligibility_terms"] = " | ".join(item.get("raw_text", "") for item in final_eligibility_items)
    doc_meta["final_bid_eligibility_evidence"] = " | ".join(item.get("context", "") for item in final_eligibility_items[:5])
    g2b_match = choose_g2b_match(doc_meta, g2b_records or [])
    g2b_metadata = apply_g2b_metadata(doc_meta, g2b_match, date_summary)
    doc_meta.update(date_summary)
    v1_blocks = rfp.build_v1_blocks(doc_meta, clean_text)
    for block in v1_blocks:
        block["doc_key"] = doc_meta["doc_key"]
        block["doc_id"] = doc_meta["doc_id"]
        block["pilot_doc_id"] = doc_meta["pilot_doc_id"]
        block["source_format"] = source_format
        block["parser_version"] = "p4_v1_clean_text"
        refresh_p4_block_metadata(block, doc_meta)
    v2_text_blocks = rfp.build_v1_blocks(doc_meta, non_table_clean_text)
    v2_text_blocks = [{**block, "parser_version": "p4_v2_non_table_text", "block_id": block["block_id"].replace("_v1_", "_v2_"), "source_format": source_format} for block in v2_text_blocks]
    for block in v2_text_blocks:
        block["doc_key"] = doc_meta["doc_key"]
        block["doc_id"] = doc_meta["doc_id"]
        block["pilot_doc_id"] = doc_meta["pilot_doc_id"]
        refresh_p4_block_metadata(block, doc_meta)
    table_blocks = build_hwpx_table_blocks(doc_meta, extracted.get("tables", []))
    summaries = {
        "budget_summary": budget_summary,
        "date_summary": date_summary,
        "period_summary": period_summary,
        "final_eligibility_items": final_eligibility_items,
        "final_submission_document_names": final_submission_document_names,
        "submission_logistics": submission_logistics,
    }
    fact_blocks = build_compact_fact_blocks(doc_meta, clean_text, summaries)
    v2_blocks = v2_text_blocks + table_blocks + fact_blocks
    chunks_v1, source_store_v1 = blocks_to_retrieval_records(v1_blocks)
    chunks_v2, source_store_v2 = blocks_to_retrieval_records(v2_blocks)
    business_types = infer_business_types(doc_meta.get("project_name", ""), clean_text[:4000])
    doc_summary.update({
        "final_budget": budget_summary.get("final_budget", ""),
        "final_budget_krw": budget_summary.get("final_budget_krw", ""),
        "final_budget_status": budget_summary.get("final_budget_status", ""),
        "final_notice_id": doc_meta.get("final_notice_id", ""),
        "notice_id_status": doc_meta.get("notice_id_status", ""),
        "final_project_duration": period_summary.get("final_project_duration", ""),
        "final_bid_deadline": doc_meta.get("final_bid_deadline", ""),
        "bid_deadline_status": doc_meta.get("bid_deadline_status", ""),
        "final_submission_documents": ", ".join(final_submission_document_names),
        "final_bid_eligibility_terms": truncate(doc_meta.get("final_bid_eligibility_terms", ""), 500),
        "proposal_submission_date_hint": submission_logistics.get("proposal_submission_date_hint", ""),
        "proposal_submission_method_hint": submission_logistics.get("proposal_submission_method_hint", ""),
        "proposal_submission_place_hint": submission_logistics.get("proposal_submission_place_hint", ""),
        "business_type_candidates": ", ".join(business_types),
        "chunk_count_v1": len(chunks_v1),
        "chunk_count_v2": len(chunks_v2),
        "source_store_count_v1": len(source_store_v1),
        "source_store_count_v2": len(source_store_v2),
        "fact_status": ",".join(sorted(set(block.get("fact_status", "") for block in fact_blocks if block.get("fact_status")))) if fact_blocks else "missing",
        "fact_confidence": ",".join(sorted(set(block.get("fact_confidence", "") for block in fact_blocks if block.get("fact_confidence")))) if fact_blocks else "missing",
        "fact_block_count": len(fact_blocks),
        "embedded_table_block_count": sum(1 for block in table_blocks if block.get("embed_enabled")),
        "suppressed_table_block_count": sum(1 for block in table_blocks if not block.get("embed_enabled")),
    })
    doc_summary.update({key: as_scalar(value) for key, value in g2b_metadata.items()})
    return {
        "summary": doc_summary,
        "chunks_v1": chunks_v1,
        "source_store_v1": source_store_v1,
        "chunks_v2": chunks_v2,
        "source_store_v2": source_store_v2,
    }


def percentile(values, q: float):
    values = sorted(values)
    return 0 if not values else values[int((len(values) - 1) * q)]


def validate_outputs(limit: int, output_dir: Path, summary_df: pd.DataFrame, chunks: list[dict], source_store: list[dict], version: str) -> dict:
    chunk_ids = [row.get("chunk_id") for row in chunks]
    source_ids = [row.get("source_store_id") for row in source_store]
    source_id_set = set(source_ids)
    source_refs = [row.get("source_ref", {}).get("source_store_id", "") for row in chunks]
    content_lens = [len(row.get("content", "")) for row in chunks]
    missing_refs = [ref for ref in source_refs if ref not in source_id_set]
    chunks_path = output_dir / f"chunks_{version}_{limit}.jsonl"
    source_path = output_dir / f"source_store_{version}_{limit}.jsonl"
    if version == "v2":
        chunks_path = output_dir / f"chunks_v2_{limit}.jsonl"
        source_path = output_dir / f"source_store_{limit}.jsonl"
    report = {
        "output_dir": str(output_dir),
        "version": version,
        "document_count": int(len(summary_df)),
        "parse_success_docs": int((summary_df["parser_status"] == "success").sum()),
        "parse_failed_docs": int((summary_df["parser_status"] != "success").sum()),
        "source_format_counts": summary_df["source_format"].value_counts(dropna=False).to_dict(),
        "total_table_count": int(summary_df["table_count"].sum()),
        "total_image_count": int(summary_df["image_count"].sum()),
        "chunk_count": int(len(chunks)),
        "source_store_count": int(len(source_store)),
        "duplicate_doc_id_count": int(summary_df["doc_id"].duplicated().sum()),
        "duplicate_chunk_id_count": int(len(chunk_ids) - len(set(chunk_ids))),
        "duplicate_source_store_id_count": int(len(source_ids) - len(set(source_ids))),
        "missing_source_store_ref": int(len(missing_refs)),
        "missing_doc_key_count": int((summary_df["doc_key"].astype(str).str.strip() == "").sum()),
        "embed_enabled_count": int(sum(1 for row in chunks if row.get("embed_enabled"))),
        "chunk_type_counts": dict(Counter(row.get("chunk_type", "") for row in chunks)),
        "avg_content_len": round(sum(content_lens) / len(content_lens), 2) if content_lens else 0,
        "p50_content_len": int(percentile(content_lens, 0.50)),
        "p95_content_len": int(percentile(content_lens, 0.95)),
        "max_content_len": int(max(content_lens) if content_lens else 0),
        "chunks_jsonl_file_size_mib": round(chunks_path.stat().st_size / 1024 / 1024, 2) if chunks_path.exists() else 0,
        "source_store_file_size_mib": round(source_path.stat().st_size / 1024 / 1024, 2) if source_path.exists() else 0,
        "date_policy": "bid_deadline_only; posted date and bid-start date are not used",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if "is_eval_ground_truth" in summary_df.columns:
        eval_count = int(summary_df["is_eval_ground_truth"].astype(bool).sum())
        report["eval_physical_source_docs_included"] = eval_count
        report["expected_eval_physical_source_docs"] = eval_count if limit == P4_125_LIMIT else None
        report["additional_sampled_docs"] = int(len(summary_df) - eval_count)
    if "g2b_match_status" in summary_df.columns:
        report["g2b_match_status_counts"] = summary_df["g2b_match_status"].value_counts(dropna=False).to_dict()
        report["g2b_active_match_count"] = int((summary_df["g2b_match_status"] == "matched_active").sum())
        report["g2b_bid_deadline_count"] = int(((summary_df["g2b_match_status"] == "matched_active") & (summary_df["g2b_bid_deadline"].astype(str).str.strip() != "")).sum()) if "g2b_bid_deadline" in summary_df.columns else 0
        report["g2b_cancelled_only_count"] = int((summary_df["g2b_match_status"] == "cancelled_only").sum())
        report["g2b_ambiguous_active_count"] = int((summary_df["g2b_match_status"] == "ambiguous_active").sum())
    if version == "v2":
        report["fact_status_counts"] = dict(Counter(row.get("fact_status", "") for row in chunks if row.get("chunk_type") == "fact_candidates"))
        report["fact_confidence_counts"] = dict(Counter(row.get("fact_confidence", "") for row in chunks if row.get("chunk_type") == "fact_candidates"))
        report["fact_type_counts"] = dict(Counter(row.get("fact_type", "") for row in chunks if row.get("chunk_type") == "fact_candidates"))
        report["low_confidence_fact_embedded_count"] = int(sum(1 for row in chunks if row.get("chunk_type") == "fact_candidates" and row.get("fact_confidence") == "low" and row.get("embed_enabled")))
        report["table_role_counts"] = dict(Counter(row.get("metadata", {}).get("table_role", "") for row in chunks if row.get("chunk_type") == "table"))
        report["suppressed_table_chunk_count"] = int(sum(1 for row in chunks if row.get("chunk_type") == "table" and not row.get("embed_enabled")))
        row_type_counter = Counter()
        merged_cell_count = 0
        for source in source_store:
            table = source.get("table_structure") or {}
            if not table:
                continue
            merged_cell_count += int((table.get("table_shape") or {}).get("merged_cell_count") or 0)
            for row in table.get("rows") or []:
                row_type_counter[row.get("row_type", "")] += 1
        report["row_type_counts"] = dict(row_type_counter)
        report["merged_cell_count"] = int(merged_cell_count)
    fail_reasons = []
    if report["duplicate_chunk_id_count"] > 0:
        fail_reasons.append("duplicate_chunk_id")
    if report["duplicate_source_store_id_count"] > 0:
        fail_reasons.append("duplicate_source_store_id")
    if report["missing_source_store_ref"] > 0:
        fail_reasons.append("missing_source_store_ref")
    if report.get("low_confidence_fact_embedded_count", 0) > 0:
        fail_reasons.append("low_confidence_fact_embedded")
    report["status"] = "PASS" if not fail_reasons else "FAIL"
    report["fail_reasons"] = fail_reasons
    return report


def write_readme(output_dir: Path, limit: int, report_v1: dict, report_v2: dict) -> None:
    readme = f"""# parsing_p4_hwpx_{limit} Retrieval-Ready Corpus

HWPX 우선 파싱을 적용한 P4 mini-pilot corpus입니다.

## 파일 설명

| 파일 | 설명 |
|---|---|
| `chunks_v1_{limit}.jsonl` | clean text baseline retrieval index입니다. R0 비교 실험에 사용합니다. |
| `chunks_v2_{limit}.jsonl` | HWPX table-aware structured retrieval index입니다. Chroma 적재 기본 입력입니다. |
| `source_store_v1_{limit}.jsonl` | v1 상세 근거 조회용 파일입니다. Chroma metadata의 `source_store_id`로 연결할 때만 사용합니다. |
| `source_store_{limit}.jsonl` | v2 상세 근거 조회용 파일입니다. 큰 table 구조는 여기에 보관하고 Chroma metadata에는 연결 key만 둡니다. |
| `metadata_light_{limit}.xlsx` | 문서별 파싱 요약과 5,000자 preview를 담은 참고용 파일입니다. |
| `validation_report_v1.json` | v1 검증 결과입니다. |
| `validation_report.json` | v2 검증 결과입니다. |
| `manifest.json` | corpus 생성 조건과 파일명을 기록합니다. |
| `json_key_description.md` | 125 corpus의 JSON/JSONL key, metadata, source_store, fact/table 정책 설명서입니다. |
| `chroma_load_example.py` | Colab/GCP에서 `chunks_v2_{limit}.jsonl`을 Chroma에 적재하는 실행 예시입니다. 버전 충돌 방어 코드를 포함합니다. |
| `embedding_retrieval_eval_p4_hwpx_{limit}_quickcheck.ipynb` | `chunks_v2_{limit}.jsonl`을 Chroma에 적재하고 KoE5 dense/BM25/RRF/reranker retrieval 실험을 실행하는 노트북입니다. |

## 사용 기준

- Chroma 적재 시 `chunk_id`는 `ids`, `content`는 `documents`, `metadata`는 `metadatas`로 사용합니다.
- retrieval 담당자는 기본적으로 `chunks_v2_{limit}.jsonl`에서 `embed_enabled=true`인 record의 `content`를 임베딩 대상으로 사용합니다.
- `chunk_type=toc`는 구조 파악용으로 보존하되 기본 임베딩 대상에서 제외합니다.
- 기본 generation 입력은 Chroma가 반환한 `documents + metadatas`입니다.
- 표 원형, 긴 원문 근거, UI 원문 보기, 정성평가처럼 Chroma chunk만으로 부족할 때만 `source_ref.source_store_id`로 `source_store_{limit}.jsonl`을 조회합니다.
- `rows`, `full_table_json`, 긴 원문, OCR 전문은 Chroma metadata에 넣지 않습니다.
- G2B 보강 메타데이터는 `data/g2b_master_cleaned.csv`에서 공고번호와 괄호 안 `입찰마감일시`만 사용합니다. `게시일시`는 사용하지 않습니다.
- 원본 RFP, source_store, Chroma DB, embedding cache는 GitHub 업로드 대상이 아닙니다.

## Validation Summary

### v1

```json
{json.dumps(report_v1, ensure_ascii=False, indent=2)}
```

### v2

```json
{json.dumps(report_v2, ensure_ascii=False, indent=2)}
```
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def write_chroma_load_guide(output_dir: Path, limit: int) -> None:
    guide = f"""# P4 HWPX {limit} Chroma 적재 가이드

P4 HWPX {limit} corpus를 Colab 또는 GCP에서 Chroma에 적재하고 retrieval quickcheck를 돌릴 때 필요한 기준입니다.

## 1. 어떤 파일을 써야 하나?

기본 retrieval 실험은 아래 파일을 사용합니다.

```text
outputs/parsing_p4_hwpx_{limit}/chunks_v2_{limit}.jsonl
```

비교 실험이 필요하면 v1 baseline도 사용할 수 있습니다.

```text
outputs/parsing_p4_hwpx_{limit}/chunks_v1_{limit}.jsonl
```

`metadata_light_{limit}.xlsx`는 사람이 검토하기 위한 참고 파일입니다. 임베딩 대상이 아닙니다.
`source_store_{limit}.jsonl`은 긴 원문/표 구조 근거 조회용입니다. Chroma metadata에 그대로 넣지 않습니다.

## 2. Chroma에 넣는 매핑

| P4 JSONL key | Chroma 입력 | 설명 |
|---|---|---|
| `chunk_id` | `ids` | Chroma 고유 ID입니다. 중복되면 안 됩니다. |
| `content` | `documents` | 임베딩할 검색용 텍스트입니다. |
| `metadata` | `metadatas` | `source_file`, `doc_id`, `chunk_type` 등 필터/출처 정보입니다. |

중요 원칙:

```text
본문은 documents(content)에 넣고,
metadata에는 필터링/출처/연결용 값만 넣습니다.
```

metadata에 긴 원문, table 전체 JSON, OCR 전문, rows/list/dict를 그대로 넣지 않습니다.

## 3. 반드시 필터링할 것

적재 전 아래 조건을 적용하세요.

```python
row.get("embed_enabled") is True
row.get("chunk_type") != "toc"
row.get("content", "").strip() != ""
```

`toc`는 구조 파악용으로 보존하지만 기본 임베딩에서는 제외합니다.
low-confidence fact chunk도 JSONL에는 남아 있지만 `embed_enabled=false`이면 적재하지 않습니다.

## 4. P4 125 quickcheck 노트북

사용자 공유용 quickcheck 노트북은 아래 파일입니다.

```text
notebooks/rag/embedding_retrieval_eval_p4_hwpx_{limit}_quickcheck.ipynb
```

`RUN_MODE` 하나로 적재/평가 범위를 바꿉니다.

| RUN_MODE | Chroma 적재 범위 | 평가 문항 | 용도 |
|---|---:|---:|---|
| `smoke` | 앞 1,000개 embed chunk | 5문항 | 패키지/경로/적재 sanity check |
| `quick` | 전체 embed chunk | 30문항 | 기본 빠른 retrieval check |
| `full` | 전체 embed chunk | eligible eval 전체 | 전체 평가 |

`quick`가 기본값입니다.

## 5. Colab 환경에서 주의할 점

Colab에서는 Google Drive에 Chroma DB를 직접 만들지 않는 것이 좋습니다.
Drive는 동기화 I/O가 느리고 파일이 많이 생기면 멈춘 것처럼 보일 수 있습니다.

권장:

```text
Chroma path: /content/chroma_p4_hwpx_{limit}
결과 CSV/JSON: /content/drive/MyDrive/.../outputs/...
```

즉, Chroma DB는 런타임 로컬에 만들고, 최종 결과 CSV/JSON만 Drive에 저장하세요.
런타임을 끊으면 Chroma DB는 사라져도 됩니다. JSONL에서 다시 만들 수 있습니다.

## 6. 버전 충돌 방지

quickcheck 노트북 첫 셀은 아래 충돌을 감지하고 재설치합니다.

```text
chromadb ↔ opentelemetry 버전 불일치
sentence-transformers/transformers ↔ tokenizers 버전 불일치
```

특히 아래 오류를 방지하도록 구성했습니다.

```text
ImportError: cannot import name '_ON_EMIT_RECURSION_COUNT_KEY' from 'opentelemetry.context'
ImportError: tokenizers>=0.22.0,<=0.23.0 is required ... found tokenizers==0.23.1
```

첫 셀에서 설치가 실행된 뒤에도 import 오류가 계속되면 런타임을 한 번 재시작하고 위에서부터 다시 실행하세요.

## 7. 적재 전 sanity check

확인할 것:

```python
import json
from collections import Counter
from pathlib import Path

path = Path("outputs/parsing_p4_hwpx_{limit}/chunks_v2_{limit}.jsonl")
chunk_types = Counter()
fact_types = Counter()
rows = embed_rows = duplicate_ids = empty_content = 0
seen_ids = set()

with path.open("r", encoding="utf-8") as f:
    for line in f:
        row = json.loads(line)
        rows += 1
        chunk_id = row.get("chunk_id", "")
        duplicate_ids += int(chunk_id in seen_ids)
        seen_ids.add(chunk_id)
        empty_content += int(not str(row.get("content", "")).strip())
        embed_rows += int(bool(row.get("embed_enabled")))
        chunk_types[row.get("chunk_type", "")] += 1
        if row.get("chunk_type") == "fact_candidates":
            fact_types[row.get("fact_type", "")] += 1

print("rows:", rows)
print("embed_rows:", embed_rows)
print("duplicate_chunk_id:", duplicate_ids)
print("empty_content:", empty_content)
print("chunk_types:", dict(chunk_types))
print("fact_types:", dict(fact_types))
```

기준:

```text
duplicate_chunk_id = 0
empty_content = 0
toc는 기본 적재 제외
```

## 8. G2B 날짜 메타데이터 정책

G2B 보강 메타데이터는 보수적으로 사용합니다.

- `입찰공고번호`는 확실한 active match일 때만 final 공고번호로 사용합니다.
- 날짜는 `게시일시(입찰마감일시)`의 괄호 안 `입찰마감일시`만 사용합니다.
- `게시일시`는 사용하지 않습니다.
- `취소공고`는 audit metadata에는 남길 수 있지만 final 공고번호/마감일로 사용하지 않습니다.

## 9. GitHub 업로드 주의

아래는 GitHub에 올리지 않는 것을 기본으로 합니다.

```text
source_store_*.jsonl
Chroma DB
embedding cache
원본 HWP/HWPX/PDF
대용량 결과 파일
```

노트북, 코드, README/guide, validation report, manifest만 GitHub 공유 대상으로 두는 것이 안전합니다.
"""
    (output_dir / "CHROMA_LOAD_GUIDE.md").write_text(guide, encoding="utf-8")


def write_p4_corpus(project_root: str | Path, limit: int = 250, verbose: bool = True, progress_every: int = 1) -> dict:
    def log(message: str) -> None:
        if verbose:
            print(message, flush=True)

    project_root = Path(project_root).resolve()
    output_dir = project_root / "outputs" / f"parsing_p4_hwpx_{limit}"
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"[p4] project_root={project_root}")
    log(f"[p4] output_dir={output_dir}")
    log(f"[p4] limit={limit}")
    sample_df, selection_report = load_sample_rows(project_root, limit=limit, output_dir=output_dir)
    log(f"[selection] documents={len(sample_df)} eval={int(sample_df['is_eval_ground_truth'].astype(bool).sum()) if 'is_eval_ground_truth' in sample_df else 'n/a'}")
    log(f"[selection] rule={selection_report.get('selection_rule', '')}")
    if int(limit) == P4_125_LIMIT:
        log(f"[selection] hard_distractors={selection_report.get('hard_distractor_count', 0)}")
    hwpx_lookup = build_hwpx_lookup(project_root / "data" / "hwpx_664")
    log(f"[inputs] hwpx_lookup={len(hwpx_lookup)}")
    g2b_records = load_g2b_records(project_root)
    log(f"[inputs] g2b_records={len(g2b_records)} date_policy=bid_deadline_only")
    artifacts = []
    total_docs = len(sample_df)
    for doc_index, (_, row) in enumerate(sample_df.iterrows(), start=1):
        doc_started = time.time()
        artifact = build_doc_artifacts(row.to_dict(), project_root, hwpx_lookup, g2b_records)
        artifacts.append(artifact)
        if verbose and (doc_index == 1 or doc_index == total_docs or doc_index % max(1, progress_every) == 0):
            summary = artifact["summary"]
            log(
                "[parse] "
                f"{doc_index:03d}/{total_docs:03d} "
                f"status={summary.get('parser_status')} "
                f"format={summary.get('source_format')} "
                f"tables={summary.get('table_count')} "
                f"g2b={summary.get('g2b_match_status')} "
                f"fact_blocks={summary.get('fact_block_count')} "
                f"chunks_v2={summary.get('chunk_count_v2')} "
                f"elapsed={time.time() - doc_started:.2f}s "
                f"file={summary.get('source_file')}"
            )
    summary_df = pd.DataFrame([item["summary"] for item in artifacts])
    chunks_v1, source_store_v1, chunks_v2, source_store_v2 = [], [], [], []
    for item in artifacts:
        chunks_v1.extend(item["chunks_v1"])
        source_store_v1.extend(item["source_store_v1"])
        chunks_v2.extend(item["chunks_v2"])
        source_store_v2.extend(item["source_store_v2"])
    log(f"[aggregate] chunks_v1={len(chunks_v1)} source_store_v1={len(source_store_v1)}")
    log(f"[aggregate] chunks_v2={len(chunks_v2)} source_store_v2={len(source_store_v2)}")
    paths = {
        "chunks_v1": output_dir / f"chunks_v1_{limit}.jsonl",
        "source_store_v1": output_dir / f"source_store_v1_{limit}.jsonl",
        "chunks_v2": output_dir / f"chunks_v2_{limit}.jsonl",
        "source_store_v2": output_dir / f"source_store_{limit}.jsonl",
        "metadata_light": output_dir / f"metadata_light_{limit}.xlsx",
        "pilot_docs": output_dir / f"pilot_docs_{limit}.csv",
        "manifest": output_dir / "manifest.json",
        "validation_v1": output_dir / "validation_report_v1.json",
        "validation_v2": output_dir / "validation_report.json",
    }
    write_jsonl(paths["chunks_v1"], chunks_v1)
    log(f"[write] {paths['chunks_v1'].name}")
    write_jsonl(paths["source_store_v1"], source_store_v1)
    log(f"[write] {paths['source_store_v1'].name}")
    write_jsonl(paths["chunks_v2"], chunks_v2)
    log(f"[write] {paths['chunks_v2'].name}")
    write_jsonl(paths["source_store_v2"], source_store_v2)
    log(f"[write] {paths['source_store_v2'].name}")
    summary_df.to_excel(paths["metadata_light"], index=False)
    log(f"[write] {paths['metadata_light'].name}")
    if not paths["pilot_docs"].exists() or int(limit) != P4_125_LIMIT:
        sample_df.to_csv(paths["pilot_docs"], index=False, encoding="utf-8-sig")
    log(f"[write] {paths['pilot_docs'].name}")
    report_v1 = validate_outputs(limit, output_dir, summary_df, chunks_v1, source_store_v1, "v1")
    report_v2 = validate_outputs(limit, output_dir, summary_df, chunks_v2, source_store_v2, "v2")
    log(f"[validation] v1_status={report_v1['status']} v2_status={report_v2['status']}")
    log(f"[validation] v2_chunk_count={report_v2['chunk_count']} embed_enabled={report_v2['embed_enabled_count']}")
    paths["validation_v1"].write_text(json.dumps(report_v1, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["validation_v2"].write_text(json.dumps(report_v2, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "corpus_name": f"p4_hwpx_{limit}",
        "corpus_version": "v2_hwpx_precision_fact_table_aware",
        "baseline_version": "v1_clean_text",
        "document_count": limit,
        "sample_source": selection_report.get("sample_source", paths["pilot_docs"].name),
        "selection": selection_report,
        "parser_version": PARSER_VERSION,
        "chunks_v1_file": paths["chunks_v1"].name,
        "chunks_v2_file": paths["chunks_v2"].name,
        "source_store_v1_file": paths["source_store_v1"].name,
        "source_store_v2_file": paths["source_store_v2"].name,
        "pilot_docs_file": paths["pilot_docs"].name,
        "metadata_light_file": paths["metadata_light"].name,
        "validation_v1_file": paths["validation_v1"].name,
        "validation_v2_file": paths["validation_v2"].name,
        "chroma_load_guide_file": "CHROMA_LOAD_GUIDE.md",
        "json_key_description_file": "json_key_description.md",
        "chroma_load_example_file": "chroma_load_example.py",
        "chunk_max_chars": CHUNK_MAX_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
        "hwpx_parsing_used": True,
        "fact_types": list(FACT_TYPE_ALIASES),
        "table_embed_policy": {
            "embed_high_signal_tables": True,
            "suppress_layout_toc_sparse_tables": True,
            "high_signal_keywords": HIGH_SIGNAL_TABLE_KEYWORDS,
            "low_signal_keywords": LOW_SIGNAL_TABLE_KEYWORDS,
        },
        "g2b_merge_policy": {
            "source_file": f"data/{G2B_MASTER_FILENAME}",
            "date_fields_used": ["입찰마감일시"],
            "posted_date_used": False,
            "bid_deadline_extraction": "only the parenthesized value in 게시일시(입찰마감일시) is parsed",
            "cancelled_notice_policy": "취소공고 candidates are recorded for audit but never used as final notice/deadline",
            "duplicate_resolution": "prefer active notices, higher title/agency match score, higher notice revision suffix, 공고 유형 priority, then later 입찰마감일시; no 게시일자 sorting",
            "ambiguous_policy": "close active matches with different notice bases are marked ambiguous_active and not merged as final metadata",
        },
        "github_upload_policy": "commit code, notebooks, README/guide, manifest, validation reports only; do not commit source_store, original files, Chroma DB, or embedding cache",
        "created_at": report_v2["created_at"],
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output_dir, limit, report_v1, report_v2)
    write_chroma_load_guide(output_dir, limit)
    table_preview_rows = []
    for source in source_store_v2:
        if source.get("source_type") != "table":
            continue
        table = source.get("table_structure") or {}
        table_preview_rows.append({
            "source_file": source.get("source_file"),
            "section_path": source.get("section_path"),
            "table_shape": json.dumps(table.get("table_shape", {}), ensure_ascii=False),
            "columns_candidate": " | ".join(table.get("columns_candidate", [])[:12]),
            "table_role": table.get("table_role", ""),
            "table_signal_score": table.get("table_signal_score", 0),
            "table_embed_reason": table.get("table_embed_reason", ""),
            "preview": truncate(source.get("full_text", ""), 700),
        })
        if len(table_preview_rows) >= 30:
            break
    table_preview_df = pd.DataFrame(table_preview_rows)
    if not table_preview_df.empty:
        table_preview_df.to_csv(output_dir / f"table_preview_{limit}.csv", index=False, encoding="utf-8-sig")
        log(f"[write] table_preview_{limit}.csv")
    log("[done] P4 corpus generation complete")
    return {
        "output_dir": output_dir,
        "summary_df": summary_df,
        "report_v1": report_v1,
        "report_v2": report_v2,
        "manifest": manifest,
        "table_preview_df": table_preview_df,
    }
