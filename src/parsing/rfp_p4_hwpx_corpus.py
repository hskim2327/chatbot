from __future__ import annotations

from collections import Counter, defaultdict
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
    lines = [f"[표 | 섹션: {section} | rows: {shape.get('row_count', 0)} | cols: {shape.get('col_count', 0)}]"]
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


def choose_parse_source(doc_row: dict, project_root: Path, hwpx_lookup: dict[str, Path]) -> tuple[Path, str]:
    source_file = str(doc_row.get("source_file", ""))
    norm = rfp.normalize_doc_name(source_file)
    file_type = str(doc_row.get("file_type", "")).lower()
    if file_type == "hwp" and norm in hwpx_lookup:
        return hwpx_lookup[norm], "hwpx"
    source_path = Path(str(doc_row.get("source_path", "")))
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
        if chunk_type == "table":
            source_record["table_structure"] = block.get("structured_data", {})
        source_records.append(source_record)
        for part_index, content in enumerate(rfp.split_text_with_overlap(text, max_chars=CHUNK_MAX_CHARS, overlap=CHUNK_OVERLAP), start=1):
            content = content.strip()
            if not content:
                continue
            content_hash = sha1_short(content, 12)
            chunk_id = f"{doc_id}_{chunk_type}_{block_token}_part_{part_index:03d}_{content_hash}"
            embed_enabled = block_type != "toc"
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
            if chunk_type == "fact_candidates":
                metadata.update({"fact_type": block.get("fact_type", ""), "fact_status": fact_status, "fact_confidence": fact_confidence})
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


def build_compact_fact_block(doc_meta: dict, clean_text: str, summaries: dict) -> dict | None:
    parts, evidence, fact_types = [], [], []
    budget = summaries.get("budget_summary", {})
    if budget.get("final_budget") and budget.get("final_budget_status") == "extracted":
        parts.append(f"사업금액: {budget.get('final_budget')}")
        fact_types.append("budget")
        evidence.append(budget.get("final_budget_evidence", ""))
    period = summaries.get("period_summary", {})
    if period.get("final_project_duration"):
        parts.append(f"사업기간: {period.get('final_project_duration')}")
        fact_types.append("duration")
        evidence.append(period.get("final_project_duration_evidence", ""))
    if period.get("final_maintenance_period"):
        parts.append(f"무상유지보수기간: {period.get('final_maintenance_period')}")
        fact_types.append("maintenance")
    if period.get("final_warranty_period"):
        parts.append(f"하자담보책임기간: {period.get('final_warranty_period')}")
        fact_types.append("warranty")
    dates = summaries.get("date_summary", {})
    if dates.get("final_bid_deadline"):
        parts.append(f"입찰마감일: {dates.get('final_bid_deadline')}")
        fact_types.append("bid_deadline")
        evidence.append(dates.get("bid_deadline_evidence", ""))
    submission_names = summaries.get("final_submission_document_names", [])
    if submission_names:
        parts.append("제출서류: " + ", ".join(submission_names[:25]))
        fact_types.append("submission_documents")
    logistics = summaries.get("submission_logistics", {})
    if logistics.get("proposal_submission_date_hint"):
        parts.append("제안서 제출일자 후보: " + logistics["proposal_submission_date_hint"])
        fact_types.append("proposal_submission_date")
    if logistics.get("proposal_submission_method_hint"):
        parts.append("제출방법 후보: " + logistics["proposal_submission_method_hint"])
        fact_types.append("submission_method")
    if logistics.get("proposal_submission_place_hint"):
        parts.append("제출장소 후보: " + logistics["proposal_submission_place_hint"])
        fact_types.append("submission_place")
    eligibility_terms = []
    for item in summaries.get("final_eligibility_items", [])[:12]:
        for term in item.get("matched_terms") or []:
            if term not in eligibility_terms:
                eligibility_terms.append(term)
    if eligibility_terms:
        parts.append("입찰참가자격 키워드: " + ", ".join(eligibility_terms[:20]))
        fact_types.append("eligibility")
    business_types = infer_business_types(doc_meta.get("project_name", ""), clean_text[:4000])
    if business_types:
        parts.append("사업유형 후보: " + ", ".join(business_types))
        fact_types.append("business_type")
    if not parts:
        return None
    confidence = "high"
    status = "extracted"
    if not budget.get("final_budget") or not period.get("final_project_duration"):
        confidence = "medium"
    if len(parts) <= 2:
        confidence = "low"
        status = "needs_review"
    text = " | ".join(parts)
    return {
        "parser_version": "p4_hwpx_retrieval_ready",
        "pilot_doc_id": doc_meta["pilot_doc_id"],
        "doc_id": doc_meta["doc_id"],
        "doc_key": doc_meta["doc_key"],
        "norm_name": doc_meta["norm_name"],
        "source_file": doc_meta["source_file"],
        "source_format": doc_meta.get("source_format", ""),
        "file_type": doc_meta.get("file_type", ""),
        **rfp.block_common_metadata(doc_meta),
        "block_id": f"{doc_meta['pilot_doc_id']}_v2_fact_0001",
        "block_type": "fact_candidates",
        "section_path": ["핵심 후보 정보"],
        "section_type": "핵심 후보 정보",
        "text": text,
        "structured_data": {"fact_types": fact_types, "parts": parts},
        "exact_terms": rfp.extract_exact_terms(text, doc_meta),
        "dates": rfp.extract_dates(text),
        "amounts": rfp.extract_amount_strings(text),
        "char_len": len(text),
        "fact_type": "|".join(fact_types),
        "fact_status": status,
        "fact_confidence": confidence,
        "evidence_text_short": truncate(" / ".join(str(x) for x in evidence if x), 500),
    }


def build_hwpx_table_blocks(doc_meta: dict, tables: list[dict]) -> list[dict]:
    blocks = []
    for table in tables:
        block_seq = int(table.get("table_seq", len(blocks) + 1))
        text_for_embedding = table.get("body_text", "")
        if not text_for_embedding.strip():
            continue
        blocks.append({
            "parser_version": "p4_hwpx_table_aware",
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "doc_key": doc_meta["doc_key"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "source_format": doc_meta.get("source_format", ""),
            "file_type": doc_meta.get("file_type", ""),
            **rfp.block_common_metadata(doc_meta),
            "block_id": f"{doc_meta['pilot_doc_id']}_v2_table_{block_seq:04d}",
            "block_type": "table",
            "section_path": list(table.get("section_path") or ["문서 시작"]),
            "section_type": rfp.classify_section(text_for_embedding),
            "text": text_for_embedding,
            "structured_data": {
                "table_shape": table.get("table_shape", {}),
                "columns_candidate": table.get("columns_candidate", []),
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


def build_doc_artifacts(doc_row: dict, project_root: Path, hwpx_lookup: dict[str, Path]) -> dict:
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
        "final_bid_deadline": "",
        "final_submission_documents": "",
        "final_bid_eligibility_terms": "",
        "business_type_candidates": "",
        "chunk_count_v1": 0,
        "chunk_count_v2": 0,
        "source_store_count_v1": 0,
        "source_store_count_v2": 0,
        "fact_status": "",
        "fact_confidence": "",
        "text_preview_5000": "",
    }
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
    date_summary = rfp.select_final_dates(date_candidates)
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
    v1_blocks = rfp.build_v1_blocks(doc_meta, clean_text)
    for block in v1_blocks:
        block["doc_key"] = doc_meta["doc_key"]
        block["doc_id"] = doc_meta["doc_id"]
        block["pilot_doc_id"] = doc_meta["pilot_doc_id"]
        block["source_format"] = source_format
        block["parser_version"] = "p4_v1_clean_text"
    v2_text_blocks = rfp.build_v1_blocks(doc_meta, non_table_clean_text)
    v2_text_blocks = [{**block, "parser_version": "p4_v2_non_table_text", "block_id": block["block_id"].replace("_v1_", "_v2_"), "source_format": source_format} for block in v2_text_blocks]
    for block in v2_text_blocks:
        block["doc_key"] = doc_meta["doc_key"]
        block["doc_id"] = doc_meta["doc_id"]
        block["pilot_doc_id"] = doc_meta["pilot_doc_id"]
    table_blocks = build_hwpx_table_blocks(doc_meta, extracted.get("tables", []))
    summaries = {
        "budget_summary": budget_summary,
        "date_summary": date_summary,
        "period_summary": period_summary,
        "final_eligibility_items": final_eligibility_items,
        "final_submission_document_names": final_submission_document_names,
        "submission_logistics": submission_logistics,
    }
    fact_block = build_compact_fact_block(doc_meta, clean_text, summaries)
    v2_blocks = v2_text_blocks + table_blocks
    if fact_block:
        v2_blocks.append(fact_block)
    chunks_v1, source_store_v1 = blocks_to_retrieval_records(v1_blocks)
    chunks_v2, source_store_v2 = blocks_to_retrieval_records(v2_blocks)
    business_types = infer_business_types(doc_meta.get("project_name", ""), clean_text[:4000])
    doc_summary.update({
        "final_budget": budget_summary.get("final_budget", ""),
        "final_budget_krw": budget_summary.get("final_budget_krw", ""),
        "final_budget_status": budget_summary.get("final_budget_status", ""),
        "final_project_duration": period_summary.get("final_project_duration", ""),
        "final_bid_deadline": date_summary.get("final_bid_deadline", ""),
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
        "fact_status": fact_block.get("fact_status", "") if fact_block else "missing",
        "fact_confidence": fact_block.get("fact_confidence", "") if fact_block else "missing",
    })
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
        "document_count": int(limit),
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
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if version == "v2":
        report["fact_status_counts"] = dict(Counter(row.get("fact_status", "") for row in chunks if row.get("chunk_type") == "fact_candidates"))
        report["fact_confidence_counts"] = dict(Counter(row.get("fact_confidence", "") for row in chunks if row.get("chunk_type") == "fact_candidates"))
        report["low_confidence_fact_embedded_count"] = int(sum(1 for row in chunks if row.get("chunk_type") == "fact_candidates" and row.get("fact_confidence") == "low" and row.get("embed_enabled")))
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

## 사용 기준

- Chroma 적재 시 `chunk_id`는 `ids`, `content`는 `documents`, `metadata`는 `metadatas`로 사용합니다.
- retrieval 담당자는 기본적으로 `chunks_v2_{limit}.jsonl`에서 `embed_enabled=true`인 record의 `content`를 임베딩 대상으로 사용합니다.
- `chunk_type=toc`는 구조 파악용으로 보존하되 기본 임베딩 대상에서 제외합니다.
- 기본 generation 입력은 Chroma가 반환한 `documents + metadatas`입니다.
- 표 원형, 긴 원문 근거, UI 원문 보기, 정성평가처럼 Chroma chunk만으로 부족할 때만 `source_ref.source_store_id`로 `source_store_{limit}.jsonl`을 조회합니다.
- `rows`, `full_table_json`, 긴 원문, OCR 전문은 Chroma metadata에 넣지 않습니다.
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


def write_p4_corpus(project_root: str | Path, limit: int = 250) -> dict:
    project_root = Path(project_root).resolve()
    output_dir = project_root / "outputs" / f"parsing_p4_hwpx_{limit}"
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_df = load_p3_sample_rows(project_root, limit=limit)
    hwpx_lookup = build_hwpx_lookup(project_root / "data" / "hwpx_664")
    artifacts = []
    for _, row in sample_df.iterrows():
        artifacts.append(build_doc_artifacts(row.to_dict(), project_root, hwpx_lookup))
    summary_df = pd.DataFrame([item["summary"] for item in artifacts])
    chunks_v1, source_store_v1, chunks_v2, source_store_v2 = [], [], [], []
    for item in artifacts:
        chunks_v1.extend(item["chunks_v1"])
        source_store_v1.extend(item["source_store_v1"])
        chunks_v2.extend(item["chunks_v2"])
        source_store_v2.extend(item["source_store_v2"])
    paths = {
        "chunks_v1": output_dir / f"chunks_v1_{limit}.jsonl",
        "source_store_v1": output_dir / f"source_store_v1_{limit}.jsonl",
        "chunks_v2": output_dir / f"chunks_v2_{limit}.jsonl",
        "source_store_v2": output_dir / f"source_store_{limit}.jsonl",
        "metadata_light": output_dir / f"metadata_light_{limit}.xlsx",
        "manifest": output_dir / "manifest.json",
        "validation_v1": output_dir / "validation_report_v1.json",
        "validation_v2": output_dir / "validation_report.json",
    }
    write_jsonl(paths["chunks_v1"], chunks_v1)
    write_jsonl(paths["source_store_v1"], source_store_v1)
    write_jsonl(paths["chunks_v2"], chunks_v2)
    write_jsonl(paths["source_store_v2"], source_store_v2)
    summary_df.to_excel(paths["metadata_light"], index=False)
    report_v1 = validate_outputs(limit, output_dir, summary_df, chunks_v1, source_store_v1, "v1")
    report_v2 = validate_outputs(limit, output_dir, summary_df, chunks_v2, source_store_v2, "v2")
    paths["validation_v1"].write_text(json.dumps(report_v1, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["validation_v2"].write_text(json.dumps(report_v2, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "corpus_name": f"p4_hwpx_{limit}",
        "corpus_version": "v2_hwpx_table_aware",
        "baseline_version": "v1_clean_text",
        "document_count": limit,
        "sample_source": f"outputs/parsing_p3_{limit}/metadata_light_{limit}.xlsx",
        "chunks_v1_file": paths["chunks_v1"].name,
        "chunks_v2_file": paths["chunks_v2"].name,
        "source_store_v1_file": paths["source_store_v1"].name,
        "source_store_v2_file": paths["source_store_v2"].name,
        "metadata_light_file": paths["metadata_light"].name,
        "chunk_max_chars": CHUNK_MAX_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
        "hwpx_parsing_used": True,
        "created_at": report_v2["created_at"],
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output_dir, limit, report_v1, report_v2)
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
            "preview": truncate(source.get("full_text", ""), 700),
        })
        if len(table_preview_rows) >= 30:
            break
    table_preview_df = pd.DataFrame(table_preview_rows)
    if not table_preview_df.empty:
        table_preview_df.to_csv(output_dir / f"table_preview_{limit}.csv", index=False, encoding="utf-8-sig")
    return {
        "output_dir": output_dir,
        "summary_df": summary_df,
        "report_v1": report_v1,
        "report_v2": report_v2,
        "manifest": manifest,
        "table_preview_df": table_preview_df,
    }
