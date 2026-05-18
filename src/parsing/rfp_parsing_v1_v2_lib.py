from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import ast
import csv
import hashlib
import json
import math
import re
import unicodedata
import zlib

import olefile
import pandas as pd
from pypdf import PdfReader
from tqdm.auto import tqdm


PILOT_TOTAL_DOCS = 250
EVAL_GROUND_TRUTH_DOCS_TOTAL = 62
# The eval set has 62 extension-normalized ground-truth names, but two names
# point to the same physical source file after the known Incheon airport alias.
EVAL_PHYSICAL_SOURCE_DOCS_TOTAL = 61
ADDITIONAL_SAMPLED_DOCS = PILOT_TOTAL_DOCS - EVAL_PHYSICAL_SOURCE_DOCS_TOTAL

ARTIFACT_REMOVE_TOKENS = {
    "浵", "汫", "楴", "普", "浫", "牦", "沤", "潣", "爔", "蕀", "遠", "浥",
}
CONFIRMED_KEEP_HANJA_TOKENS = {
    "新", "舊",
    "甲", "乙", "丙", "丁",
    "案", "內", "外", "共",
    "過", "未", "無", "有",
}
KEEP_HANJA_RUNS = {
    "甲乙", "甲乙丙", "甲乙丙丁",
    "案內", "內外", "共有",
    "未定", "無償", "有償",
}
KNOWN_FILENAME_ALIASES = {
    "인천공항운서비스㈜": "인천공항운영서비스㈜",
}

RFP_SECTION_KEYWORDS = {
    "사업개요": ["사업명", "사업개요", "사업기간", "소요예산", "사업예산", "사업비", "계약방식", "선정방법"],
    "추진체계": ["추진체계", "추진역할", "추진목표", "추진방향", "추진일정", "추진방안"],
    "제안요청내용": ["제안요청", "요구사항", "기능요구사항", "성능요구사항", "데이터", "구축", "고도화", "과업내용"],
    "입찰참가자격": ["입찰참가자격", "참가자격", "자격요건", "공동수급", "하도급", "대기업", "중소기업"],
    "평가_협상": ["기술평가", "가격평가", "종합평가", "협상적격", "우선협상", "동점자", "배점", "평가기준"],
    "제출안내": ["제출기한", "제출마감", "제출방법", "제출장소", "제출서류", "구비서류", "제안서 제출"],
    "붙임_서식": ["붙임", "별지", "별첨", "서식", "첨부"],
}
BUDGET_KEYWORDS = ["소요예산", "사업예산", "예산액", "추정가격", "기초금액", "사업비", "사업금액", "계약금액", "배정예산", "부가세", "VAT"]
SUBMISSION_KEYWORDS = ["제출서류", "구비서류", "입찰서류", "제안서", "가격제안서", "사업자등록증", "실적증명서", "서약서", "확약서"]
TABLE_HINT_KEYWORDS = sorted(set(
    BUDGET_KEYWORDS
    + SUBMISSION_KEYWORDS
    + ["평가기준", "배점", "기술평가", "가격평가", "마감일", "제출기한", "사업기간", "입찰참가자격"]
))
SUBMISSION_DOC_TERMS = [
    "제안서", "제안요약서", "발표자료", "가격제안서", "입찰참가신청서", "입찰서", "산출내역서",
    "사업자등록증", "법인등기부등본", "인감증명서", "사용인감계", "위임장", "재직증명서",
    "청렴계약", "보안서약서", "서약서", "확약서", "동의서", "확인서", "실적증명서",
    "신용평가등급확인서", "경쟁입찰참가자격등록증", "중소기업확인서", "직접생산확인증명서",
    "소프트웨어사업자", "공동수급협정서", "합의각서", "하도급계획서", "원본", "사본", "USB",
]
GENERIC_SUBMISSION_TERMS = {"원본", "사본", "USB"}

MAJOR_HEADING_MARKER_RE = re.compile(
    r"^\s*((제\s*\d+\s*[장절관항])|([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.．]?))\s*"
)
NUMBERED_HEADING_MARKER_RE = re.compile(r"^\s*((\d+\s*[.)])|([가-하]\s*[.)]))\s*")
AMOUNT_RE = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit>억원|억\s*원|백만원|천원|만원|원)")
QUANTITY_RE = re.compile(r"\d+\s*(부|매|식|개|권|set|SET|copy|copies)")
DATE_RE = re.compile(
    r"(\d{4}\s*[.년/-]\s*\d{1,2}\s*[.월/-]\s*\d{1,2}\s*일?|\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
TIME_RE = re.compile(r"(?P<hour>\d{1,2})\s*[:시]\s*(?P<minute>\d{2})?")
PUBLISH_DATE_KEYWORDS = ["공고일", "공고 일", "공고기간", "공개일", "게시일", "등록일", "공고", "공시"]
BID_START_DATE_KEYWORDS = ["접수개시", "접수 시작", "입찰개시", "입찰 시작", "제출개시", "제출 시작", "개시일", "시작일", "부터"]
BID_DEADLINE_DATE_KEYWORDS = ["마감", "제출기한", "제출 기한", "제출마감", "접수마감", "입찰마감", "입찰서 제출", "제안서 제출", "까지"]
DATE_SECTION_HINTS = ["입찰", "제안", "공고", "접수", "제출", "마감", "개찰", "일정"]
CODE_RE = re.compile(r"\b[A-Z]{1,8}[-_]\d{1,5}(?:[-_]\d{1,5})?\b|[A-Z]{2,}[A-Z0-9_-]{2,}")
NOTICE_ID_KEYWORD_RE = re.compile(r"(입\s*찰\s*)?공\s*고\s*번\s*호")
NOTICE_ID_TITLE_RE = re.compile(r"입\s*찰\s*공\s*고\s*제\s*\d{4}")
NOTICE_ID_VALUE_PATTERNS = [
    re.compile(r"R\d{2}[A-Z]{2}\d{6,}", re.I),
    re.compile(r"\d{8,}"),
    re.compile(r"(?:[가-힣A-Za-z0-9()·._-]+\s*)?제\s*\d{4}\s*[-–—]\s*\d+\s*호"),
    re.compile(r"\d{2}\s*[-–—]\s*[가-힣A-Za-z0-9]+(?:\s*[가-힣A-Za-z0-9]+)*\s*[-–—]\s*\d+"),
]
NOTICE_ID_BLANK_FORM_RE = re.compile(r"(기재|작성|공란|해당|입력|번호\s*$)")
TOC_DOT_LEADER_RE = re.compile(r"[·.]{5,}\s*\d+\s*$")
HWPTAG_PARA_TEXT = 67
CHUNK_MAX_CHARS = 1000
CHUNK_OVERLAP = 150
P2_OUTPUT_NAME = "parsing_p2_250"
P2_VERSION_LABEL = "p2_chunkfix_toc_clean"
P2_METADATA_EXCEL_NAME = "rfp_parsing_metadata_250_p2_chunkfix_toc_clean.xlsx"
P2_OUTPUT_DESCRIPTION = "P2 - chunk_id 중복 수정, toc 분리, artifact cleaner 보강"
CONTROL_ARTIFACT_RE = re.compile(r"[\u0400-\u04ff\u0800-\u0fff]+")
CONTROL_ARTIFACT_WITH_LATIN_RE = re.compile(
    r"[\u0400-\u04ff\u0800-\u0fff]\s*[\u0100-\u017f]?"
    r"|[\u0100-\u017f]\s*[\u0400-\u04ff\u0800-\u0fff]"
)
CONTROL_ARTIFACT_TOKENS = ("╦", "ࡦ", "ྠ", "ೖ", "ଔ", "䵴", "Ā", "ȃ")
NORMAL_HANJA_KEEP_CHARS = set("現無有乙新舊內外")


def make_project_paths(
    project_dir: str | Path,
    parsing_output_name: str = "parsing_v1_v2_2차",
    parsing_version_label: str = "v1_v2_current",
    metadata_excel_name: str | None = None,
) -> dict[str, Path]:
    project_dir = Path(project_dir).resolve()
    data_dir = project_dir / "data"
    outputs_dir = project_dir / "outputs"
    parsing_output_dir = outputs_dir / parsing_output_name
    if metadata_excel_name is None:
        if parsing_output_name == "parsing_v1_v2_revision":
            metadata_excel_name = "rfp_parsing_metadata_250_v1_v2_revision.xlsx"
        elif parsing_output_name == P2_OUTPUT_NAME:
            metadata_excel_name = P2_METADATA_EXCEL_NAME
        else:
            metadata_excel_name = "rfp_parsing_metadata_250.xlsx"
    outputs_dir.mkdir(exist_ok=True)
    parsing_output_dir.mkdir(parents=True, exist_ok=True)
    if parsing_output_name == "parsing_v1_v2_revision":
        output_description = "V1/V2 수정버전"
    elif parsing_output_name == P2_OUTPUT_NAME:
        output_description = P2_OUTPUT_DESCRIPTION
    else:
        output_description = "V1/V2 parsing output"
    return {
        "project_dir": project_dir,
        "data_dir": data_dir,
        "original_data_dir": data_dir / "original_data_list",
        "eval_dir": data_dir / "eval",
        "metadata_xlsx": data_dir / "data_list_advanced.xlsx",
        "fallback_metadata_xlsx": data_dir / "data_list_reparsed.xlsx",
        "outputs_dir": outputs_dir,
        "parsing_output_dir": parsing_output_dir,
        "parsing_output_name": parsing_output_name,
        "parsing_version_label": parsing_version_label,
        "output_description": output_description,
        "pilot_docs_csv": parsing_output_dir / "pilot_docs_250.csv",
        "doc_parse_summary_csv": parsing_output_dir / "doc_parse_summary.csv",
        "parsed_blocks_v1_jsonl": parsing_output_dir / "parsed_blocks_v1.jsonl",
        "parsed_blocks_v2_jsonl": parsing_output_dir / "parsed_blocks_v2.jsonl",
        "chunks_v1_jsonl": parsing_output_dir / "chunks_v1.jsonl",
        "chunks_v2_jsonl": parsing_output_dir / "chunks_v2.jsonl",
        "parsing_summary_json": parsing_output_dir / "parsing_summary.json",
        "parsing_summary_md": parsing_output_dir / "parsing_summary.md",
        "metadata_excel": parsing_output_dir / metadata_excel_name,
    }


def normalize_doc_name(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = Path(text).name
    while re.search(r"\.(hwp|hwpx|pdf|json)$", text, flags=re.I):
        text = re.sub(r"\.(hwp|hwpx|pdf|json)$", "", text, flags=re.I).strip()
    text = re.sub(r"\s+", " ", text)
    for old, new in KNOWN_FILENAME_ALIASES.items():
        text = text.replace(old, new)
    return text.strip()


def infer_doc_title_fields(source_file: str, norm_name: str | None = None) -> tuple[str, str]:
    """Infer issuer and project name from the source filename, not external metadata."""
    norm = normalize_doc_name(norm_name or source_file)
    if "_" in norm:
        issuer, project_name = norm.split("_", 1)
        return issuer.strip(), project_name.strip()
    return "", norm.strip()


def sanitize_doc_meta_for_db(doc_meta: dict) -> dict:
    """Drop teacher-provided metadata fields before building DB-facing outputs."""
    cleaned = dict(doc_meta)
    issuer, project_name = infer_doc_title_fields(cleaned.get("source_file", ""), cleaned.get("norm_name", ""))
    cleaned["issuer"] = issuer
    cleaned["project_name"] = project_name
    cleaned["external_notice_id"] = ""
    cleaned["notice_id"] = ""
    cleaned["final_notice_id"] = ""
    cleaned["notice_id_status"] = "missing"
    cleaned["notice_id_evidence"] = ""
    cleaned["notice_round"] = ""
    cleaned["metadata_budget"] = ""
    cleaned["published_at"] = ""
    cleaned["bid_start"] = ""
    cleaned["bid_deadline"] = ""
    return cleaned


def db_metadata_fields_from_source(source: dict) -> dict:
    issuer, project_name = infer_doc_title_fields(source.get("source_file", ""), source.get("norm_name", ""))
    return {
        "metadata_source": "",
        "project_name": project_name,
        "issuer": issuer,
        "metadata_budget": "",
        "notice_id": "",
        "notice_round": "",
        "published_at": "",
        "bid_start": "",
        "bid_deadline": "",
        "external_notice_id": "",
        "final_notice_id": "",
        "notice_id_status": "missing",
        "notice_id_evidence": "",
    }


def parse_ground_truth_docs(raw_value) -> list[str]:
    text = "" if raw_value is None else str(raw_value).strip()
    if not text or text.lower() == "nan":
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
            if isinstance(parsed, str):
                return [parsed]
            if isinstance(parsed, (list, tuple, set)):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [text]


def stable_doc_id(norm_name: str) -> str:
    digest = hashlib.sha1(norm_name.encode("utf-8")).hexdigest()[:10]
    return f"doc_{digest}"


def load_eval_ground_truth_docs(eval_dir: Path) -> pd.DataFrame:
    rows = []
    for csv_path in sorted(eval_dir.glob("*.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for doc in parse_ground_truth_docs(row.get("ground_truth_docs")):
                    norm = normalize_doc_name(doc)
                    if norm:
                        rows.append({
                            "eval_file": csv_path.name,
                            "question_id": row.get("id"),
                            "ground_truth_doc_raw": doc,
                            "norm_name": norm,
                        })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["norm_name", "question_count", "eval_files", "raw_examples"])
    return (
        df.groupby("norm_name", as_index=False)
        .agg(
            question_count=("question_id", "nunique"),
            eval_files=("eval_file", lambda s: ", ".join(sorted(set(map(str, s))))),
            raw_examples=("ground_truth_doc_raw", lambda s: " | ".join(sorted(set(map(str, s)))[:3])),
        )
        .sort_values(["question_count", "norm_name"], ascending=[False, True])
        .reset_index(drop=True)
    )


def build_original_inventory(original_data_dir: Path) -> pd.DataFrame:
    paths = sorted(
        [*original_data_dir.rglob("*.hwp"), *original_data_dir.rglob("*.hwpx"), *original_data_dir.rglob("*.pdf")],
        key=lambda p: str(p).lower(),
    )
    return pd.DataFrame([{
        "norm_name": normalize_doc_name(path.name),
        "doc_id": stable_doc_id(normalize_doc_name(path.name)),
        "source_file": path.name,
        "source_path": str(path),
        "file_type": path.suffix.lower().lstrip("."),
    } for path in paths])


def load_metadata(metadata_path: Path, fallback_path: Path) -> pd.DataFrame:
    path = metadata_path if metadata_path.exists() else fallback_path
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_excel(path)
    if "파일명" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["norm_name"] = df["파일명"].map(normalize_doc_name)
    df["metadata_source"] = path.name
    return df


def first_existing_value(row: dict, candidates: list[str], default="") -> str:
    for col in candidates:
        value = row.get(col)
        if value is not None and not (isinstance(value, float) and math.isnan(value)) and str(value).strip():
            return str(value).strip()
    return default


def build_metadata_lookup(metadata: pd.DataFrame) -> dict[str, dict]:
    if metadata.empty or "norm_name" not in metadata.columns:
        return {}
    lookup = {}
    for _, row in metadata.iterrows():
        norm = row.get("norm_name")
        if norm and norm not in lookup:
            lookup[norm] = row.to_dict()
    return lookup


def score_sampling_candidate(source_file: str, meta: dict | None) -> tuple[int, str]:
    meta = meta or {}
    parts = [source_file]
    for col in ["사업명", "사업 요약", "텍스트", "발주 기관", "사업 금액", "공고명"]:
        value = meta.get(col)
        if value is not None:
            parts.append(str(value))
    text = "\n".join(parts)[:30000]
    groups = {
        "budget": BUDGET_KEYWORDS,
        "submission_docs": SUBMISSION_KEYWORDS,
        "evaluation_table": ["평가기준", "평가 기준", "배점", "기술평가", "가격평가", "종합평가"],
        "appendix_forms": ["붙임", "별지", "별첨", "서식", "첨부"],
        "eligibility": ["입찰참가자격", "참가자격", "공동수급", "하도급", "실적", "인증"],
    }
    weights = {"budget": 5, "submission_docs": 7, "evaluation_table": 6, "appendix_forms": 4, "eligibility": 4}
    score = 0
    reasons = []
    for group, keywords in groups.items():
        hit_count = sum(1 for kw in keywords if kw in text)
        if hit_count:
            score += weights[group] * hit_count
            reasons.append(group)
    if source_file.lower().endswith(".pdf"):
        score += 1
        reasons.append("pdf_included")
    return score, "+".join(sorted(set(reasons))) if reasons else "filler_sample"


def build_pilot_docs(paths: dict[str, Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eval_docs_df = load_eval_ground_truth_docs(paths["eval_dir"])
    original_inventory_df = build_original_inventory(paths["original_data_dir"])
    metadata_df = load_metadata(paths["metadata_xlsx"], paths["fallback_metadata_xlsx"])
    archived_pilot_candidates = [
        paths["parsing_output_dir"] / "250" / "pilot_docs_250.csv",
        paths["project_dir"] / "outputs" / "parsing_v1_v2_2차" / "250" / "pilot_docs_250.csv",
        paths["project_dir"] / "outputs" / "parsing_v1_v2_2차" / "pilot_docs_250.csv",
    ]
    archived_pilot_csv = next((path for path in archived_pilot_candidates if path.exists()), None)
    if (metadata_df.empty or paths.get("parsing_output_name") == "parsing_v1_v2_revision") and archived_pilot_csv is not None:
        pilot = pd.read_csv(archived_pilot_csv, encoding="utf-8-sig")
        sanitized_rows = [db_metadata_fields_from_source(row.to_dict()) for _, row in pilot.iterrows()]
        for key in sanitized_rows[0]:
            pilot[key] = [row[key] for row in sanitized_rows]
        assert len(pilot) == PILOT_TOTAL_DOCS, f"archived pilot 문서 수가 {PILOT_TOTAL_DOCS}개가 아닙니다: {len(pilot)}"
        assert int(pilot["is_eval_ground_truth"].astype(bool).sum()) == EVAL_PHYSICAL_SOURCE_DOCS_TOTAL
        pilot.to_csv(paths["pilot_docs_csv"], index=False, encoding="utf-8-sig")
        return pilot, eval_docs_df, original_inventory_df, metadata_df
    metadata_lookup = build_metadata_lookup(metadata_df)

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
        score, _ = score_sampling_candidate(source["source_file"], meta)
        selected_norms.add(norm)
        selected_rows.append({
            **source,
            "is_eval_ground_truth": True,
            "sampling_reason": "eval_ground_truth",
            "sample_score": score,
            "eval_question_count": int(eval_row["question_count"]),
            **db_metadata_fields_from_source(source),
        })

    if missing_eval_docs:
        raise FileNotFoundError("원본에서 매칭되지 않은 eval 문서가 있습니다: " + " | ".join(missing_eval_docs))

    remaining = []
    for _, source in original_inventory_df.iterrows():
        norm = source["norm_name"]
        if norm in selected_norms:
            continue
        meta = metadata_lookup.get(norm, {})
        score, reason = score_sampling_candidate(source["source_file"], meta)
        remaining.append({
            **source.to_dict(),
            "is_eval_ground_truth": False,
            "sampling_reason": reason,
            "sample_score": score,
            "eval_question_count": 0,
            **db_metadata_fields_from_source(source),
        })

    remaining = sorted(remaining, key=lambda r: (-int(r["sample_score"]), r["file_type"] != "hwp", r["source_file"]))
    selected_rows.extend(remaining[:PILOT_TOTAL_DOCS - len(selected_rows)])

    pilot = pd.DataFrame(selected_rows).reset_index(drop=True)
    pilot.insert(0, "pilot_index", range(1, len(pilot) + 1))
    pilot["pilot_doc_id"] = pilot["pilot_index"].map(lambda i: f"P{i:03d}")

    assert len(pilot) == PILOT_TOTAL_DOCS, f"pilot 문서 수가 {PILOT_TOTAL_DOCS}개가 아닙니다: {len(pilot)}"
    assert int(pilot["is_eval_ground_truth"].sum()) == EVAL_PHYSICAL_SOURCE_DOCS_TOTAL
    assert pilot["norm_name"].nunique() == len(pilot), "pilot 문서 norm_name 중복이 있습니다."

    pilot.to_csv(paths["pilot_docs_csv"], index=False, encoding="utf-8-sig")
    return pilot, eval_docs_df, original_inventory_df, metadata_df


def is_packed_ascii_garbage(text: str) -> bool:
    if len(text) < 2:
        return False
    raw = b"".join(ch.encode("utf-16le", errors="ignore") for ch in text)
    if not raw:
        return False
    printable = sum(32 <= b <= 126 for b in raw)
    ascii_letters = sum((65 <= b <= 90) or (97 <= b <= 122) for b in raw)
    return printable / len(raw) >= 0.8 and ascii_letters >= len(text)


def remove_control_artifacts(text: str) -> str:
    text = CONTROL_ARTIFACT_WITH_LATIN_RE.sub(" ", str(text or ""))
    text = CONTROL_ARTIFACT_RE.sub(" ", text)
    for token in CONTROL_ARTIFACT_TOKENS:
        text = text.replace(token, " ")
    return text


def compact_label_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def contains_label_keyword(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
    text = str(text or "")
    compact = compact_label_text(text)
    return any(keyword in text or compact_label_text(keyword) in compact for keyword in keywords)


def remove_hwp_garbage(text: str) -> str:
    text = str(text or "").replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    for token in ARTIFACT_REMOVE_TOKENS:
        text = text.replace(token, " ")

    def replace_cjk_run(match):
        token = match.group(0)
        if token in KEEP_HANJA_RUNS or token in CONFIRMED_KEEP_HANJA_TOKENS:
            return token
        return " " if is_packed_ascii_garbage(token) else token

    text = re.sub(r"[\u4e00-\u9fff]{2,}", replace_cjk_run, text)
    text = re.sub(r"[\u3400-\u9fff\uf900-\ufaff][\u0100-\u02ff]", " ", text)
    text = re.sub(r"[\u0100-\u02ff][\u3400-\u9fff\uf900-\ufaff]", " ", text)
    text = re.sub(r"[\u3130-\u318f][\u0100-\u02ff]", " ", text)
    text = re.sub(r"[\u0100-\u02ff][\u3130-\u318f]", " ", text)
    text = remove_control_artifacts(text)

    cleaned_lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            continue
        has_keep_hanja = any(token in line for token in CONFIRMED_KEEP_HANJA_TOKENS) or any(
            char in line for char in NORMAL_HANJA_KEEP_CHARS
        )
        if not re.search(r"[가-힣A-Za-z0-9]", line) and not has_keep_hanja:
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_hwp_compressed(ole) -> bool:
    header = ole.openstream("FileHeader").read()
    return bool(header[36] & 1)


def decompress_hwp_stream(data: bytes, compressed: bool) -> bytes:
    if not compressed:
        return data
    try:
        return zlib.decompress(data, -15)
    except zlib.error:
        return zlib.decompress(data)


def iter_hwp_records(section_data: bytes):
    pos = 0
    size_total = len(section_data)
    while pos + 4 <= size_total:
        header = int.from_bytes(section_data[pos:pos + 4], "little")
        pos += 4
        tag_id = header & 0x3ff
        level = (header >> 10) & 0x3ff
        size = (header >> 20) & 0xfff
        if size == 0xfff:
            if pos + 4 > size_total:
                break
            size = int.from_bytes(section_data[pos:pos + 4], "little")
            pos += 4
        payload = section_data[pos:pos + size]
        pos += size
        yield tag_id, level, payload


def extract_hwp_text_raw(hwp_path: str | Path) -> dict:
    hwp_path = Path(hwp_path)
    if not olefile.isOleFile(str(hwp_path)):
        raise ValueError(f"OLE 기반 HWP 파일이 아닙니다: {hwp_path}")
    ole = olefile.OleFileIO(str(hwp_path))
    compressed = is_hwp_compressed(ole)
    section_names = sorted(
        "/".join(item)
        for item in ole.listdir(streams=True, storages=False)
        if item and item[0] == "BodyText"
    )
    raw_texts = []
    para_text_record_count = 0
    for section_name in section_names:
        raw = ole.openstream(section_name).read()
        data = decompress_hwp_stream(raw, compressed)
        for tag_id, level, payload in iter_hwp_records(data):
            if tag_id == HWPTAG_PARA_TEXT:
                para_text_record_count += 1
                text = payload.decode("utf-16le", errors="ignore")
                if text.strip():
                    raw_texts.append(text)
    ole.close()
    raw_text = "\n".join(raw_texts)
    return {
        "parser": "olefile_hwp_bodytext",
        "filename": hwp_path.name,
        "path": str(hwp_path),
        "compressed": compressed,
        "section_count": len(section_names),
        "para_text_record_count": para_text_record_count,
        "raw_text": raw_text,
    }


def extract_hwp_text(hwp_path: str | Path) -> dict:
    raw_doc = extract_hwp_text_raw(hwp_path)
    clean_text = remove_hwp_garbage(raw_doc["raw_text"])
    return {
        **raw_doc,
        "clean_text": clean_text,
        "raw_char_len": len(raw_doc["raw_text"]),
        "clean_char_len": len(clean_text),
        "parser_status": "success",
        "error": "",
    }


def extract_pdf_text(pdf_path: str | Path) -> dict:
    pdf_path = Path(pdf_path)
    reader = PdfReader(str(pdf_path))
    page_texts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append(text)
    raw_text = "\n".join(page_texts)
    clean_text = remove_hwp_garbage(raw_text)
    return {
        "parser": "pypdf_extract_text",
        "filename": pdf_path.name,
        "path": str(pdf_path),
        "compressed": None,
        "section_count": None,
        "para_text_record_count": None,
        "raw_text": raw_text,
        "clean_text": clean_text,
        "raw_char_len": len(raw_text),
        "clean_char_len": len(clean_text),
        "parser_status": "success",
        "error": "",
    }


def extract_document_text(path: str | Path) -> dict:
    path = Path(path)
    try:
        suffix = path.suffix.lower()
        if suffix == ".hwp":
            return extract_hwp_text(path)
        if suffix == ".pdf":
            return extract_pdf_text(path)
        raise ValueError(f"지원하지 않는 파일 형식입니다: {path.suffix}")
    except Exception as exc:
        return {
            "parser": "failed",
            "filename": path.name,
            "path": str(path),
            "compressed": None,
            "section_count": None,
            "para_text_record_count": None,
            "raw_text": "",
            "clean_text": "",
            "raw_char_len": 0,
            "clean_char_len": 0,
            "parser_status": "failed",
            "error": repr(exc),
        }


def normalize_line(line: str) -> str:
    line = unicodedata.normalize("NFC", str(line or "")).replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", line).strip()


def clean_lines(text: str) -> list[str]:
    return [line for line in (normalize_line(line) for line in str(text or "").splitlines()) if line]


def is_toc_like_line(line: str) -> bool:
    line = normalize_line(line)
    if not line:
        return False
    compact = re.sub(r"\s+", "", line).strip("-")
    if compact in {"목차", "目次"} or compact.upper() == "CONTENTS":
        return True
    if TOC_DOT_LEADER_RE.search(line):
        return True
    if re.match(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ0-9]+[.)]?\s+.{1,80}\s+\d{1,3}$", line):
        return True
    return False


def normalize_toc_line(line: str) -> str:
    line = normalize_line(line)
    if TOC_DOT_LEADER_RE.search(line):
        line = re.sub(r"\s*\d{1,3}\s*$", "", line)
        line = re.sub(r"[·.]{5,}", " ", line)
    return re.sub(r"\s+", " ", line).strip()


def classify_section(text: str) -> str:
    for section_type, keywords in RFP_SECTION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return section_type
    return "일반"


def is_probable_heading(line: str) -> bool:
    line = normalize_line(line)
    if not line or len(line) > 90:
        return False
    section_type = classify_section(line)
    if MAJOR_HEADING_MARKER_RE.search(line) and re.search(r"[가-힣A-Za-z]", line):
        return True
    return bool(re.match(r"^\s*(붙임|별지|별첨|서식)\s*\d*", line))


def is_table_like_line(line: str) -> bool:
    line = normalize_line(line)
    if not line or len(line) > 220:
        return False
    if TOC_DOT_LEADER_RE.search(line):
        return False
    if "\t" in line or "|" in line:
        return True
    if re.search(r"\S\s{2,}\S", line):
        return True
    if re.search(r"^[가-힣A-Za-z0-9()·ㆍ/ -]{1,25}\s*[:：]\s*\S+", line):
        return True
    if any(keyword in line for keyword in BUDGET_KEYWORDS) and AMOUNT_RE.search(line):
        return True
    if any(keyword in line for keyword in ["제출서류", "구비서류", "입찰서류"]) and QUANTITY_RE.search(line):
        return True
    if any(keyword in line for keyword in ["평가기준", "배점", "기술평가", "가격평가"]) and len(line) <= 120:
        return True
    return False


def parse_table_line_to_row(line: str) -> dict:
    line = normalize_line(line)
    if not line:
        return {"text": ""}
    if "|" in line:
        parts = [part.strip() for part in line.split("|") if part.strip()]
    elif "\t" in line:
        parts = [part.strip() for part in line.split("\t") if part.strip()]
    else:
        parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
    if len(parts) >= 2:
        return {f"col_{idx + 1}": value for idx, value in enumerate(parts)}
    label_value = re.match(r"^(?P<key>[가-힣A-Za-z0-9()·ㆍ/ -]{1,30})\s*[:：]\s*(?P<value>.+)$", line)
    if label_value:
        return {"key": label_value.group("key").strip(), "value": label_value.group("value").strip()}
    for keyword in TABLE_HINT_KEYWORDS:
        if line.startswith(keyword) and len(line) > len(keyword):
            value = line[len(keyword):].strip(" :：-–—\t")
            if value:
                return {"key": keyword, "value": value}
    return {"text": line}


def table_rows_to_embedding_text(section_path: list[str], rows: list[dict]) -> str:
    section = " > ".join(section_path) if section_path else "섹션 없음"
    lines = [f"[표 | {section}]"]
    for row in rows:
        if "key" in row and "value" in row:
            lines.append(f"{row['key']}: {row['value']}")
        elif any(key.startswith("col_") for key in row):
            values = [str(row[key]) for key in sorted(row) if key.startswith("col_")]
            lines.append(" / ".join(values))
        else:
            lines.append(str(row.get("text", "")))
    return "\n".join(line for line in lines if line.strip())


def iter_lines_with_sections(text: str):
    current_section = ["문서 시작"]
    current_section_type = "일반"
    for line in clean_lines(text):
        if is_probable_heading(line):
            current_section = [line]
            current_section_type = classify_section(line)
            yield line, current_section, current_section_type, True
        else:
            yield line, current_section, current_section_type, False


def build_v1_blocks(doc_meta: dict, clean_text: str) -> list[dict]:
    blocks = []
    toc_blocks = []
    buffer = []
    toc_buffer = []
    current_section = ["문서 시작"]
    current_section_type = "일반"
    block_seq = 0
    toc_seq = 0

    def flush_buffer():
        nonlocal block_seq, buffer
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if not text:
            buffer = []
            return
        block_seq += 1
        inferred_section_type = current_section_type
        if inferred_section_type == "일반":
            inferred_section_type = classify_section(text)
        blocks.append({
            "parser_version": "v1_section_text",
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "file_type": doc_meta["file_type"],
            **block_common_metadata(doc_meta),
            "block_id": f"{doc_meta['pilot_doc_id']}_v1_text_{block_seq:04d}",
            "block_type": "text",
            "section_path": list(current_section),
            "section_type": inferred_section_type,
            "text": text,
            "structured_data": {},
            "exact_terms": extract_exact_terms(text, doc_meta),
            "dates": extract_dates(text),
            "amounts": extract_amount_strings(text),
            "char_len": len(text),
        })
        buffer = []

    def flush_toc_buffer():
        nonlocal toc_seq, toc_buffer
        if not toc_buffer:
            return
        text = "\n".join(toc_buffer).strip()
        if not text:
            toc_buffer = []
            return
        toc_seq += 1
        toc_blocks.append({
            "parser_version": "v1_section_text",
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "file_type": doc_meta["file_type"],
            **block_common_metadata(doc_meta),
            "block_id": f"{doc_meta['pilot_doc_id']}_v1_toc_{toc_seq:04d}",
            "block_type": "toc",
            "section_path": ["목차"],
            "section_type": "목차",
            "text": text,
            "structured_data": {"toc_line_count": len(toc_buffer)},
            "exact_terms": extract_exact_terms(text, doc_meta),
            "dates": extract_dates(text),
            "amounts": extract_amount_strings(text),
            "char_len": len(text),
        })
        toc_buffer = []

    for line, section_path, section_type, is_heading in iter_lines_with_sections(clean_text):
        if is_toc_like_line(line):
            flush_buffer()
            toc_buffer.append(normalize_toc_line(line))
            continue
        if is_heading:
            flush_buffer()
            current_section = list(section_path)
            current_section_type = section_type
            buffer.append(line)
        else:
            buffer.append(line)
            if sum(len(item) for item in buffer) >= 1800:
                flush_buffer()
    flush_buffer()
    flush_toc_buffer()
    return toc_blocks + blocks


def build_v2_table_blocks(doc_meta: dict, clean_text: str) -> list[dict]:
    table_blocks = []
    run = []
    run_section = ["문서 시작"]
    block_seq = 0

    def flush_run():
        nonlocal block_seq, run
        if not run:
            return
        strong = any(any(keyword in line for keyword in TABLE_HINT_KEYWORDS) for line in run)
        if len(run) < 2 and not strong:
            run = []
            return
        rows = [parse_table_line_to_row(line) for line in run]
        text_for_embedding = table_rows_to_embedding_text(run_section, rows)
        if not text_for_embedding.strip():
            run = []
            return
        block_seq += 1
        table_blocks.append({
            "parser_version": "v2_table_aware",
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "file_type": doc_meta["file_type"],
            **block_common_metadata(doc_meta),
            "block_id": f"{doc_meta['pilot_doc_id']}_v2_table_{block_seq:04d}",
            "block_type": "table",
            "section_path": list(run_section),
            "section_type": classify_section(" ".join(run_section + run)),
            "text": text_for_embedding,
            "structured_data": {"rows": rows, "raw_lines": list(run)},
            "exact_terms": extract_exact_terms(text_for_embedding, doc_meta),
            "dates": extract_dates(text_for_embedding),
            "amounts": extract_amount_strings(text_for_embedding),
            "char_len": len(text_for_embedding),
        })
        run = []

    for line, section_path, _, is_heading in iter_lines_with_sections(clean_text):
        if is_heading:
            flush_run()
            continue
        if is_table_like_line(line):
            if not run:
                run_section = list(section_path)
            run.append(line)
        else:
            flush_run()
    flush_run()
    return table_blocks


def normalize_amount_to_krw(num_text: str, unit: str) -> int | None:
    try:
        value = float(num_text.replace(",", ""))
    except Exception:
        return None
    compact_unit = re.sub(r"\s+", "", unit)
    if "억" in compact_unit:
        value *= 100_000_000
    elif compact_unit == "백만원":
        value *= 1_000_000
    elif compact_unit == "천원":
        value *= 1_000
    elif compact_unit == "만원":
        value *= 10_000
    return int(value)


def score_budget_candidate(candidate: dict) -> tuple[int, list[str]]:
    context = str(candidate.get("context") or "")
    compact_context = compact_label_text(context)
    amount_krw = candidate.get("amount_krw")
    score = 0
    reasons = []
    strong_keywords = ["소요예산", "사업예산", "예산액", "사업비", "총사업비", "기초금액", "추정가격", "배정예산"]
    weak_keywords = ["계약금액", "부가세", "VAT", "원"]
    for keyword in strong_keywords:
        if keyword in context or keyword in compact_context:
            score += 18
            reasons.append(keyword)
    for keyword in weak_keywords:
        if keyword in context or keyword in compact_context:
            score += 5
            reasons.append(keyword)
    if amount_krw is not None:
        if amount_krw >= 10_000_000:
            score += 15
            reasons.append("large_amount")
        elif amount_krw < 1_000_000:
            score -= 10
            reasons.append("too_small")
    if any(word in context for word in ["평가", "배점", "점수", "개월", "일", "부", "명"]):
        score -= 8
        reasons.append("non_budget_hint")
    if any(word in context or word in compact_context for word in ["금액", "예산", "가격", "사업비"]):
        score += 8
        reasons.append("money_context")
    return score, reasons


def extract_budget_candidates(text: str, doc_meta: dict) -> list[dict]:
    candidates = []
    text = text or ""

    def add_candidate(raw_amount: str, amount_krw: int | None, start: int, end: int) -> None:
        context = re.sub(r"\s+", " ", text[max(0, start - 100): min(len(text), end + 120)]).strip()
        compact_context = compact_label_text(context)
        if not any(keyword in context or keyword in compact_context for keyword in BUDGET_KEYWORDS):
            return
        item = {
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "source_file": doc_meta["source_file"],
            "raw_amount": raw_amount,
            "amount_krw": amount_krw,
            "context": context,
            "line_index": (text[:start].count("\n") + 1) if text else 0,
        }
        score, reasons = score_budget_candidate(item)
        item["score"] = score
        item["score_reasons"] = reasons
        candidates.append(item)

    for match in AMOUNT_RE.finditer(text):
        add_candidate(
            match.group(0),
            normalize_amount_to_krw(match.group("num"), match.group("unit")),
            match.start(),
            match.end(),
        )

    extra_patterns = [
        re.compile(r"[₩￦]\s*(?P<num>\d{1,3}(?:,\d{3})+)"),
        re.compile(r"(?P<num>\d{1,3}(?:,\d{3}){2,})(?=\s*,?\s*(?:VAT|부가세|포함|원))", re.I),
    ]
    for pattern in extra_patterns:
        for match in pattern.finditer(text):
            amount_krw = int(match.group("num").replace(",", ""))
            add_candidate(match.group(0), amount_krw, match.start(), match.end())

    seen = set()
    unique = []
    for item in sorted(candidates, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        key = (item["raw_amount"], item["context"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:30]


def select_final_budget(candidates: list[dict]) -> dict:
    valid = [
        item for item in candidates
        if item.get("amount_krw") is not None
        and int(item.get("amount_krw") or 0) >= 1_000_000
        and int(item.get("score", 0)) >= 15
    ]
    if not valid:
        return {
            "final_budget": "",
            "final_budget_krw": "",
            "final_budget_status": "missing" if not candidates else "candidate_only",
            "final_budget_evidence": "",
        }
    best = sorted(valid, key=lambda row: (-int(row.get("score", 0)), -(row.get("amount_krw") or 0), row.get("line_index", 0)))[0]
    return {
        "final_budget": best.get("raw_amount", ""),
        "final_budget_krw": best.get("amount_krw", ""),
        "final_budget_status": "extracted",
        "final_budget_evidence": best.get("context", ""),
    }


def normalize_notice_id_value(value: str) -> str:
    value = normalize_line(value)
    value = value.strip("[](){}<> ,;:：")
    value = re.sub(r"^(입\s*찰\s*)?공\s*고\s*", "", value)
    value = re.sub(r"\s*[-–—]\s*", "-", value)
    value = re.sub(r"제\s+", "제", value)
    value = re.sub(r"\s+호\b", "호", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def digit_count(value: str) -> int:
    return sum(1 for ch in str(value) if ch.isdigit())


def notice_context_type(line: str, line_index: int) -> str:
    if any(keyword in line for keyword in ["별지", "별첨", "붙임", "서식", "제출서류", "구비서류"]):
        return "appendix_form"
    if line_index <= 80:
        return "document_top"
    if line_index <= 220:
        return "early_body"
    return "body"


def score_notice_candidate(notice_id: str, raw_text: str, line_index: int, context_type: str) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    digits = digit_count(notice_id)
    if NOTICE_ID_KEYWORD_RE.search(raw_text):
        score += 25
        reasons.append("notice_keyword")
    elif NOTICE_ID_TITLE_RE.search(raw_text):
        score += 20
        reasons.append("notice_title")
    if context_type == "document_top":
        score += 30
        reasons.append("document_top")
    elif context_type == "early_body":
        score += 15
        reasons.append("early_body")
    elif context_type == "appendix_form":
        score -= 10
        reasons.append("appendix_form")
    if re.search(r"\d{8,}", notice_id):
        score += 20
        reasons.append("long_numeric_id")
    if re.search(r"제\s*\d{4}\s*-\s*\d+\s*호", notice_id):
        score += 20
        reasons.append("complete_je_ho")
    if re.search(r"[A-Za-z가-힣]", notice_id):
        score += 5
        reasons.append("text_prefix")
    score += min(digits, 12)
    if NOTICE_ID_BLANK_FORM_RE.search(raw_text) and context_type == "appendix_form":
        score -= 10
        reasons.append("form_hint")
    return score, reasons


def extract_notice_id_summary(text: str, doc_meta: dict) -> dict:
    candidates = []
    rejected_blank_count = 0
    for line_index, line in enumerate(clean_lines(text), start=1):
        keyword_match = NOTICE_ID_KEYWORD_RE.search(line)
        title_match = NOTICE_ID_TITLE_RE.search(line)
        if not keyword_match and not title_match:
            continue
        match_start = keyword_match.start() if keyword_match else title_match.start()
        segment = line[match_start: match_start + 220]
        line_candidates = []
        for pattern in NOTICE_ID_VALUE_PATTERNS:
            line_candidates.extend(match.group(0) for match in pattern.finditer(segment))
        if not line_candidates:
            if keyword_match:
                rejected_blank_count += 1
            continue
        for raw_value in line_candidates:
            notice_id = normalize_notice_id_value(raw_value)
            if digit_count(notice_id) <= 4:
                if keyword_match:
                    rejected_blank_count += 1
                continue
            context_type = notice_context_type(line, line_index)
            score, reasons = score_notice_candidate(notice_id, line, line_index, context_type)
            candidates.append({
                "pilot_doc_id": doc_meta["pilot_doc_id"],
                "doc_id": doc_meta["doc_id"],
                "source_file": doc_meta["source_file"],
                "notice_id": notice_id,
                "score": score,
                "score_reasons": reasons,
                "context_type": context_type,
                "line_index": line_index,
                "raw_text": line,
            })

    by_notice_id = {}
    for item in candidates:
        key = item["notice_id"]
        if key not in by_notice_id or item["score"] > by_notice_id[key]["score"]:
            by_notice_id[key] = item
    unique = sorted(by_notice_id.values(), key=lambda item: (-item["score"], item["line_index"], item["notice_id"]))

    if not unique:
        status = "rejected_blank_form" if rejected_blank_count else "missing"
        return {
            "notice_id_candidates": [],
            "final_notice_id": "",
            "notice_id_status": status,
            "notice_id_evidence": "",
            "notice_id_rejected_blank_count": rejected_blank_count,
        }

    final = unique[0]
    status = "extracted"
    if len(unique) > 1 and unique[1]["score"] >= final["score"] - 8 and unique[1]["notice_id"] != final["notice_id"]:
        status = "ambiguous"
    return {
        "notice_id_candidates": unique[:20],
        "final_notice_id": final["notice_id"],
        "notice_id_status": status,
        "notice_id_evidence": final["raw_text"],
        "notice_id_rejected_blank_count": rejected_blank_count,
    }


def score_submission_candidate(line: str, matched_terms: list[str], quantity: str, required: bool) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    has_submission_context = any(keyword in line for keyword in ["제출서류", "구비서류", "입찰서류"])
    has_form_context = any(keyword in line for keyword in ["별지", "별첨", "붙임", "서식", "첨부"])
    if has_submission_context:
        score += 25
        reasons.append("submission_context")
    if matched_terms:
        score += min(len(matched_terms) * 8, 32)
        reasons.append("document_terms")
    if quantity:
        score += 10
        reasons.append("quantity")
    if required:
        score += 5
        reasons.append("required")
    else:
        score -= 5
        reasons.append("optional_hint")
    if has_form_context:
        score += 8
        reasons.append("form_context")
    if len(line) <= 120:
        score += 5
        reasons.append("short_line")
    if any(word in line for word in ["기능", "시스템", "화면", "등록", "검토", "처리"]) and not matched_terms:
        score -= 15
        reasons.append("system_requirement_hint")
    return score, reasons


def normalize_submission_doc_names(names: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for name in names:
        value = re.sub(r"\s+", "", str(name or "")).strip()
        if not value or value in GENERIC_SUBMISSION_TERMS:
            continue
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def extract_submission_doc_candidates(text: str, doc_meta: dict) -> list[dict]:
    rows = []
    for line in clean_lines(text):
        if len(line) > 260 or TOC_DOT_LEADER_RE.search(line):
            continue
        matched_terms = [term for term in SUBMISSION_DOC_TERMS if term in line]
        normalized_terms = normalize_submission_doc_names(matched_terms)
        has_submission_context = any(keyword in line for keyword in ["제출서류", "구비서류", "입찰서류"])
        if not matched_terms and not has_submission_context:
            continue
        if matched_terms and set(matched_terms).issubset(GENERIC_SUBMISSION_TERMS) and not has_submission_context:
            continue
        if not matched_terms and has_submission_context and len(line) > 120:
            continue
        quantity = QUANTITY_RE.search(line)
        required = not any(word in line for word in ["해당시", "해당 시", "필요시", "필요 시", "선택"])
        score, reasons = score_submission_candidate(line, matched_terms, quantity.group(0) if quantity else "", required)
        rows.append({
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "source_file": doc_meta["source_file"],
            "name_candidates": matched_terms,
            "normalized_names": normalized_terms,
            "quantity": quantity.group(0) if quantity else "",
            "required": required,
            "score": score,
            "score_reasons": reasons,
            "raw_text": line,
        })
    seen = set()
    unique = []
    for item in rows:
        if item["raw_text"] not in seen:
            seen.add(item["raw_text"])
            unique.append(item)
    return unique[:80]


def select_final_submission_documents(candidates: list[dict], limit: int = 30, min_score: int = 30) -> list[dict]:
    final_rows = []
    seen = set()
    for item in sorted(candidates, key=lambda row: (-int(row.get("score", 0)), row.get("raw_text", ""))):
        if int(item.get("score", 0)) < min_score:
            continue
        if not item.get("name_candidates") and not any(keyword in item.get("raw_text", "") for keyword in SUBMISSION_DOC_TERMS):
            continue
        normalized_names = normalize_submission_doc_names(item.get("normalized_names") or item.get("name_candidates") or [])
        key = tuple(normalized_names) or (item.get("raw_text", ""),)
        if key in seen:
            continue
        seen.add(key)
        final_rows.append({
            "name_candidates": item.get("name_candidates") or [],
            "normalized_names": normalized_names,
            "quantity": item.get("quantity", ""),
            "required": item.get("required", True),
            "score": item.get("score", 0),
            "score_reasons": item.get("score_reasons", []),
            "raw_text": item.get("raw_text", ""),
        })
        if len(final_rows) >= limit:
            break
    return final_rows


def flatten_final_submission_document_names(final_documents: list[dict]) -> list[str]:
    names = []
    seen = set()
    for item in sorted(final_documents, key=lambda row: (-int(row.get("score", 0)), row.get("raw_text", ""))):
        for name in normalize_submission_doc_names(item.get("normalized_names") or item.get("name_candidates") or []):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def build_submission_group_text(final_documents: list[dict]) -> str:
    groups = []
    seen = set()
    for item in final_documents:
        names = normalize_submission_doc_names(item.get("normalized_names") or item.get("name_candidates") or [])
        if not names:
            continue
        key = tuple(names)
        if key in seen:
            continue
        seen.add(key)
        groups.append(", ".join(names))
    return " | ".join(groups)


def infer_default_year(text: str, source_file: str = "") -> str:
    for source in [source_file or "", text[:5000] if text else ""]:
        match = re.search(r"20\d{2}", source)
        if match:
            return match.group(0)
    return ""


def normalize_date_value(raw_date: str, default_year: str = "") -> str:
    value = re.sub(r"\s+", "", str(raw_date or ""))
    if not value:
        return ""
    nums = re.findall(r"\d+", value)
    if len(nums) >= 3:
        year, month, day = nums[0], nums[1], nums[2]
    elif len(nums) == 2 and default_year:
        year, month, day = default_year, nums[0], nums[1]
    else:
        return value
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except Exception:
        return value


def extract_time_value(line: str, date_end: int) -> str:
    window = line[date_end: date_end + 30]
    match = TIME_RE.search(window)
    if not match:
        return ""
    hour = int(match.group("hour"))
    minute = match.group("minute") or "00"
    if hour > 24:
        return ""
    return f"{hour:02d}:{int(minute):02d}"


def classify_date_candidate(line: str) -> tuple[str, int, list[str]]:
    score = 0
    reasons = []
    date_type = "other"
    bid_context = any(keyword in line for keyword in ["입찰", "투찰", "제안서", "입찰서", "접수", "제출"])
    period_context = any(keyword in line for keyword in ["사업기간", "과업기간", "계약기간", "수행기간", "용역기간"])
    hard_deadline_keywords = ["마감", "제출기한", "제출 기한", "제출마감", "접수마감", "입찰마감", "입찰서 제출", "제안서 제출"]
    hard_start_keywords = ["접수개시", "접수 시작", "입찰개시", "입찰 시작", "제출개시", "제출 시작", "개시일", "시작일"]

    if any(keyword in line for keyword in hard_deadline_keywords) or ("까지" in line and bid_context and not period_context):
        date_type = "bid_deadline"
        score += 35
        reasons.append("deadline_keyword")
    elif any(keyword in line for keyword in hard_start_keywords) or ("부터" in line and bid_context and not period_context):
        date_type = "bid_start"
        score += 30
        reasons.append("start_keyword")
    elif any(keyword in line for keyword in PUBLISH_DATE_KEYWORDS) and not period_context:
        date_type = "published_at"
        score += 25
        reasons.append("publish_keyword")
    if bid_context:
        score += 8
        reasons.append("bid_context")
    if any(keyword in line for keyword in DATE_SECTION_HINTS):
        score += 4
        reasons.append("rfp_schedule_context")
    if "개찰" in line:
        score -= 4
        reasons.append("opening_hint")
    if period_context and date_type in {"bid_start", "bid_deadline"}:
        score -= 25
        reasons.append("project_period_hint")
    if len(line) <= 180:
        score += 5
        reasons.append("short_line")
    return date_type, score, reasons


def extract_date_candidates(text: str, doc_meta: dict, limit: int = 120) -> list[dict]:
    rows = []
    default_year = infer_default_year(text, doc_meta.get("source_file", ""))
    lines = clean_lines(text)
    for offset, line in enumerate(lines):
        line_index = offset + 1
        if len(line) > 320:
            continue
        matches = list(DATE_RE.finditer(line))
        if not matches:
            continue
        window_start = max(0, offset - 2)
        window_end = min(len(lines), offset + 3)
        context_window = " ".join(lines[window_start:window_end])
        if not any(keyword in context_window for keyword in DATE_SECTION_HINTS + BID_DEADLINE_DATE_KEYWORDS + BID_START_DATE_KEYWORDS + PUBLISH_DATE_KEYWORDS):
            continue
        for match in matches:
            raw_date = match.group(0)
            normalized_date = normalize_date_value(raw_date, default_year=default_year)
            time_value = extract_time_value(line, match.end())
            date_type, score, reasons = classify_date_candidate(context_window)
            if date_type == "other" and score < 10:
                continue
            try:
                date_year = int(str(normalized_date)[:4])
                default_year_int = int(default_year) if default_year else None
            except Exception:
                date_year = None
                default_year_int = None
            if default_year_int and date_year and date_type in {"bid_start", "bid_deadline"} and date_year not in {default_year_int, default_year_int + 1}:
                score -= 25
                reasons.append("out_of_scope_year")
            if line != context_window:
                score += 4
                reasons.append("nearby_context")
            if date_type in {"bid_start", "bid_deadline"} and score < 28:
                continue
            rows.append({
                "pilot_doc_id": doc_meta["pilot_doc_id"],
                "doc_id": doc_meta["doc_id"],
                "source_file": doc_meta["source_file"],
                "date_type": date_type,
                "raw_date": raw_date,
                "normalized_date": normalized_date,
                "time": time_value,
                "normalized_datetime": f"{normalized_date} {time_value}".strip(),
                "score": score,
                "score_reasons": reasons,
                "line_index": line_index,
                "raw_text": line,
                "context": context_window,
            })
    seen = set()
    unique = []
    for item in sorted(rows, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        key = (item["date_type"], item["normalized_datetime"], item["raw_text"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def select_final_dates(candidates: list[dict]) -> dict:
    result = {
        "final_published_at": "",
        "final_bid_start": "",
        "final_bid_deadline": "",
        "published_at_status": "missing",
        "bid_start_status": "missing",
        "bid_deadline_status": "missing",
        "published_at_evidence": "",
        "bid_start_evidence": "",
        "bid_deadline_evidence": "",
    }
    field_map = {
        "published_at": ("final_published_at", "published_at_status", "published_at_evidence"),
        "bid_start": ("final_bid_start", "bid_start_status", "bid_start_evidence"),
        "bid_deadline": ("final_bid_deadline", "bid_deadline_status", "bid_deadline_evidence"),
    }
    min_scores = {"published_at": 25, "bid_start": 28, "bid_deadline": 28}
    for date_type, (value_key, status_key, evidence_key) in field_map.items():
        typed = [
            item for item in candidates
            if item.get("date_type") == date_type
            and item.get("normalized_date")
            and int(item.get("score", 0)) >= min_scores[date_type]
        ]
        if not typed:
            continue
        def direct_period_rank(row: dict) -> tuple[int, int, int]:
            raw_text = str(row.get("raw_text", ""))
            value = str(row.get("period_value", ""))
            direct_hit = 0 if (value and value in raw_text) else 1
            type_hit = 0 if any(keyword in raw_text for keyword in PROJECT_DURATION_KEYWORDS + MAINTENANCE_PERIOD_KEYWORDS + WARRANTY_PERIOD_KEYWORDS) else 1
            return (direct_hit, type_hit, int(row.get("line_index", 0)))

        best = sorted(typed, key=lambda row: (-int(row.get("score", 0)), *direct_period_rank(row)))[0]
        result[value_key] = best.get("normalized_datetime") or best.get("normalized_date") or ""
        result[status_key] = "extracted"
        result[evidence_key] = best.get("context") or best.get("raw_text", "")
    return result


PERIOD_FORM_CONTEXT_KEYWORDS = [
    "가격제안서", "하도급 계획서", "하도급계획서", "별지", "별지서식", "별첨", "붙임", "서식", "양식", "작성", "기재", "공란",
    "유사사업실적", "사업실적증명", "계약명", "발주처", "계약금액", "사업책임기술자", "증빙번호",
]
PROJECT_DURATION_KEYWORDS = [
    "사업기간", "사업 기간", "과업기간", "과업 기간", "계약기간", "계약 기간", "수행기간", "수행 기간",
    "용역기간", "용역 기간", "추진일정", "추진 일정"
]
MAINTENANCE_PERIOD_KEYWORDS = [
    "무상유지보수기간", "무상 유지보수 기간", "무상유지보수", "무상 유지보수", "유지보수기간", "유지보수 기간",
    "유지관리기간", "유지관리 기간", "사업종료 후", "사업 종료 후"
]
WARRANTY_PERIOD_KEYWORDS = [
    "하자담보 책임기간", "하자담보책임기간", "하자담보", "하자보수 기간", "하자 보수 기간", "하자보수기간",
    "하자보증", "하자 보증"
]
DEADLINE_TERM_KEYWORDS = [
    "제출 기한", "제출기한", "제출 기한 및 일정", "통보 기한", "통보기한", "조치 기한", "조치기한",
    "납부 기한", "납부기한"
]
PERIOD_VALUE_RE = re.compile(
    r"((?:계약\s*체결일|계약일|착수일|사업\s*종료일|사업종료일|사업\s*종료|검수\s*완료일|완료일|준공일|종료일|공고일|통보일|요청일|접수일|제출일)"
    r"\s*(?:로부터|부터|이후|후)?\s*\d+\s*(?:개월|개월간|년|년간|일|일간|주|주간)\s*(?:이내|내|까지|간)?)"
    r"|(\d+\s*(?:개월|개월간|년|년간|일|일간|주|주간)\s*(?:이내|내|까지|간)?)"
)
EXTERNAL_DEADLINE_REF_RE = re.compile(r"(?:입찰|일찰)\s*공고\s*에?\s*따름|공고문\s*참조|별도\s*통보|나라장터\s*참조|조달청\s*참조")
PERIOD_VALUE_ANCHORS = ["계약", "착수", "종료", "완료", "준공", "검수", "부터", "로부터", "이내", "유지보수", "하자", "담보", "기간", "수행", "용역", "과업"]
PROJECT_PERIOD_LABEL_RE = re.compile(r"(?:사업\s*기간|과업\s*기간|용역\s*기간|계약\s*기간|수행\s*기간)\s*[:：]")
PROJECT_PERIOD_LABEL_VALUE_RE = re.compile(
    r"(?:사\s*업\s*기\s*간|과\s*업\s*기\s*간|용\s*역\s*기\s*간|계\s*약\s*기\s*간|수\s*행\s*기\s*간)"
    r"(?:\s*\)|\s*\([^)]*\))?\s*[:：]?\s*"
)
NEXT_PROJECT_FIELD_RE = re.compile(
    r"\s+(?:[가-하]\.|[0-9]+[.)]|□|○|❍|ㅇ)?\s*"
    r"(?:사업\s*비|사업\s*예산|사업\s*금액|소요\s*예산|기초\s*금액|입찰\s*방법|입찰\s*방식|대상\s*지|사업\s*주관|계약\s*방법)\s*[:：]"
)
DIRECT_PERIOD_VALUE_START_RE = re.compile(
    r"^(?:계약|착수|검수|완료|준공|사업\s*종료|20\d{2}|[′']\d{2}|\d{1,3}\s*(?:개월|일|년|주))"
)
ADMIN_DEADLINE_CONTEXT_KEYWORDS = [
    "사업수행계획서", "착수계", "착수보고", "착수 계획", "제출", "승인", "보고", "통보",
    "교체", "낙찰통지", "계약을 체결", "연장신청", "사유발생", "해명", "추가인원", "요청사항",
    "공고 및 접수기간", "접수기간", "제출기간", "공고기간",
]


def extract_period_day_count(value: str) -> int | None:
    value = str(value or "")
    match = re.search(r"(\d{1,3})\s*일", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def has_direct_project_period_label(text: str) -> bool:
    return bool(PROJECT_PERIOD_LABEL_RE.search(str(text or ""))) or contains_label_keyword(
        text,
        ["사업기간", "과업기간", "용역기간", "계약기간", "수행기간"],
    )


def has_admin_deadline_context(text: str) -> bool:
    return any(keyword in str(text or "") for keyword in ADMIN_DEADLINE_CONTEXT_KEYWORDS)


def period_value_quality(value: str) -> int:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not value:
        return -100
    if (
        re.search(r"20\s*년\s*월", value)
        or re.fullmatch(r"20\s*년", value)
        or re.search(r"\d{0,4}\s*년\s*월\s*일", value)
        or re.search(r"\b20\d?\s*\.\s*\.\s*", value)
    ):
        return -100
    score = min(len(value), 40)
    if re.fullmatch(r"20\d{2}년", value):
        score -= 35
    if any(keyword in value for keyword in ["계약", "착수", "사업종료", "사업 종료", "검수", "완료", "준공"]):
        score += 28
    if any(unit in value for unit in ["개월", "일", "주"]):
        score += 24
    if any(token in value for token in ["부터", "로부터", "~", "까지", "이내", "간"]):
        score += 18
    return score


def choose_period_value_match(text: str):
    matches = list(PERIOD_VALUE_RE.finditer(str(text or "")))
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda match: (-period_value_quality(match.group(0)), match.start()),
    )[0]


def extract_direct_project_period_value(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    for match in PROJECT_PERIOD_LABEL_VALUE_RE.finditer(text):
        tail = text[match.end(): match.end() + 160].strip(" :-–—")
        if not tail:
            continue
        stop = NEXT_PROJECT_FIELD_RE.search(" " + tail)
        if stop:
            tail = tail[: max(0, stop.start() - 1)].strip()
        tail = re.split(r"\s+(?:[가-하]\.|□|○|❍|ㅇ)\s+", tail, maxsplit=1)[0].strip()
        tail = re.split(r"\s+※", tail, maxsplit=1)[0].strip()
        if not DIRECT_PERIOD_VALUE_START_RE.search(tail):
            continue
        tail = tail.strip(" .,:;")
        if len(tail) > 90:
            tail = tail[:90].rsplit(" ", 1)[0].strip()
        if re.search(r"\d", tail) and any(token in tail for token in ["계약", "착수", "부터", "로부터", "~", "까지", "개월", "일", "년", "월"]):
            return tail
    return ""


def is_valid_period_value(value: str, period_type: str, context: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    if period_value_quality(value) <= -90:
        return False
    number_match = re.search(r"\d+", value)
    if not number_match:
        return bool(EXTERNAL_DEADLINE_REF_RE.search(value))
    number_text = number_match.group(0)
    try:
        number = int(number_text)
    except Exception:
        return False
    if len(number_text) >= 3 and number_text.startswith("0"):
        return False
    day_count = extract_period_day_count(value)
    if (
        period_type == "project_duration"
        and re.fullmatch(r"20\d{2}년", value)
        and not has_direct_project_period_label(context)
        and not extract_direct_project_period_value(context)
    ):
        return False
    if (
        period_type == "project_duration"
        and day_count is not None
        and day_count <= 20
        and not has_direct_project_period_label(context)
    ):
        return False
    if period_type == "project_duration" and number <= 2 and "년" not in value:
        return False
    if period_type == "deadline_term" and not (
        any(keyword in context for keyword in DEADLINE_TERM_KEYWORDS)
        or EXTERNAL_DEADLINE_REF_RE.search(context)
    ):
        return False
    has_clear_period_unit = any(unit in value for unit in ["개월", "일", "년", "주", "~", "까지", "부터", "로부터"])
    if re.search(r"제\s*\d+\s*(조|항|호)", context) and not has_clear_period_unit:
        return False
    return True


def classify_period_candidate(line: str, context: str) -> tuple[str, str, int, list[str], bool]:
    haystack = f"{context} {line}"
    score = 0
    reasons = []
    candidate_type = "deadline_term"
    direct_project_value_hint = extract_direct_project_period_value(line) or extract_direct_project_period_value(context)
    direct_project_label = (
        has_direct_project_period_label(line)
        or has_direct_project_period_label(context)
        or bool(direct_project_value_hint)
    )
    admin_deadline_context = has_admin_deadline_context(haystack)
    line_has_project = contains_label_keyword(line, PROJECT_DURATION_KEYWORDS)
    line_has_maintenance = contains_label_keyword(line, MAINTENANCE_PERIOD_KEYWORDS)
    line_has_warranty = contains_label_keyword(line, WARRANTY_PERIOD_KEYWORDS)
    line_has_deadline = contains_label_keyword(line, DEADLINE_TERM_KEYWORDS) or EXTERNAL_DEADLINE_REF_RE.search(line)
    context_has_project = contains_label_keyword(haystack, PROJECT_DURATION_KEYWORDS)
    context_has_maintenance = contains_label_keyword(haystack, MAINTENANCE_PERIOD_KEYWORDS)
    context_has_warranty = contains_label_keyword(haystack, WARRANTY_PERIOD_KEYWORDS)
    context_has_deadline = contains_label_keyword(haystack, DEADLINE_TERM_KEYWORDS) or EXTERNAL_DEADLINE_REF_RE.search(haystack)

    if line_has_maintenance:
        candidate_type = "maintenance_period"
        score += 32
        reasons.append("maintenance_keyword")
    elif line_has_warranty:
        candidate_type = "warranty_period"
        score += 32
        reasons.append("warranty_keyword")
    elif line_has_project:
        candidate_type = "project_duration"
        score += 32
        reasons.append("project_duration_keyword")
    elif line_has_deadline:
        candidate_type = "deadline_term"
        score += 24
        reasons.append("deadline_keyword")
    elif context_has_maintenance:
        candidate_type = "maintenance_period"
        score += 24
        reasons.append("maintenance_context")
    elif context_has_warranty:
        candidate_type = "warranty_period"
        score += 24
        reasons.append("warranty_context")
    elif context_has_project:
        candidate_type = "project_duration"
        score += 24
        reasons.append("project_duration_context")
    elif context_has_deadline:
        candidate_type = "deadline_term"
        score += 20
        reasons.append("deadline_context")

    line_has_type_keyword = contains_label_keyword(
        line,
        PROJECT_DURATION_KEYWORDS + MAINTENANCE_PERIOD_KEYWORDS + WARRANTY_PERIOD_KEYWORDS + DEADLINE_TERM_KEYWORDS,
    )
    line_value_match = choose_period_value_match(line)
    context_value_match = choose_period_value_match(context)
    if line_value_match and (line_has_type_keyword or any(anchor in line for anchor in PERIOD_VALUE_ANCHORS)):
        value_match = line_value_match
    else:
        value_match = context_value_match
    external_ref = EXTERNAL_DEADLINE_REF_RE.search(line) or EXTERNAL_DEADLINE_REF_RE.search(context)
    value = ""
    if value_match:
        value = re.sub(r"\s+", " ", value_match.group(0)).strip()
        if is_valid_period_value(value, candidate_type, haystack):
            score += 18
            reasons.append("period_value")
        else:
            score -= 20
            reasons.append("invalid_period_value")
    elif external_ref:
        value = re.sub(r"\s+", " ", external_ref.group(0)).strip()
        score += 14
        reasons.append("external_deadline_reference")

    direct_project_value = ""
    if candidate_type == "project_duration" and direct_project_label:
        direct_project_value = direct_project_value_hint
    if direct_project_value and period_value_quality(direct_project_value) >= period_value_quality(value):
        value = direct_project_value
        score += 18
        reasons.append("direct_project_period_value")

    day_count = extract_period_day_count(value)
    if direct_project_label and candidate_type == "project_duration":
        score += 22
        reasons.append("direct_project_period_label")
    if admin_deadline_context:
        reasons.append("admin_deadline_context")
        if candidate_type == "project_duration" and not direct_project_label and (day_count is None or day_count <= 30):
            candidate_type = "deadline_term"
            score -= 26
            reasons.append("reclassified_to_deadline_term")
        elif candidate_type == "project_duration" and day_count is not None and day_count <= 20:
            score -= 12
            reasons.append("short_day_admin_context")
    if candidate_type == "project_duration" and day_count is not None and day_count <= 20 and not direct_project_label:
        score -= 24
        reasons.append("short_day_without_project_label")

    if len(line) <= 180:
        score += 5
        reasons.append("short_line")
    if contains_label_keyword(haystack, ["계약", "착수", "사업", "제출", "통보", "조치", "납부", "유지보수", "하자"]):
        score += 5
        reasons.append("domain_context")
    is_form_context = contains_label_keyword(f"{line} {context}", PERIOD_FORM_CONTEXT_KEYWORDS)
    if is_form_context:
        score -= 18
        reasons.append("form_context_candidate_only")
    return candidate_type, value, score, reasons, is_form_context


def extract_period_candidates(text: str, doc_meta: dict, limit: int = 120) -> list[dict]:
    rows = []
    lines = clean_lines(text)
    trigger_keywords = PROJECT_DURATION_KEYWORDS + MAINTENANCE_PERIOD_KEYWORDS + WARRANTY_PERIOD_KEYWORDS + DEADLINE_TERM_KEYWORDS
    for offset, line in enumerate(lines):
        if len(line) > 360 or TOC_DOT_LEADER_RE.search(line):
            continue
        window_start = max(0, offset - 1)
        window_end = min(len(lines), offset + 2)
        context = " ".join(lines[window_start:window_end])
        if not contains_label_keyword(context, trigger_keywords) and not EXTERNAL_DEADLINE_REF_RE.search(context):
            continue
        candidate_type, value, score, reasons, is_form_context = classify_period_candidate(line, context)
        if not value and score < 35:
            continue
        rows.append({
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "source_file": doc_meta["source_file"],
            "period_type": candidate_type,
            "period_value": value,
            "score": score,
            "score_reasons": reasons,
            "is_form_context": is_form_context,
            "line_index": offset + 1,
            "raw_text": line,
            "context": context,
        })
    seen = set()
    unique = []
    for item in sorted(rows, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        key = (item["period_type"], item["period_value"], item["raw_text"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def select_final_periods(candidates: list[dict]) -> dict:
    result = {
        "final_project_duration": "",
        "final_project_duration_evidence": "",
        "final_maintenance_period": "",
        "final_maintenance_period_evidence": "",
        "final_warranty_period": "",
        "final_warranty_period_evidence": "",
        "final_deadline_terms": "",
        "final_deadline_terms_evidence": "",
    }
    field_map = {
        "project_duration": ("final_project_duration", "final_project_duration_evidence", 38),
        "maintenance_period": ("final_maintenance_period", "final_maintenance_period_evidence", 38),
        "warranty_period": ("final_warranty_period", "final_warranty_period_evidence", 38),
    }
    for period_type, (value_key, evidence_key, min_score) in field_map.items():
        typed = [
            item for item in candidates
            if item.get("period_type") == period_type
            and item.get("period_value")
            and is_valid_period_value(item.get("period_value", ""), period_type, item.get("context", ""))
            and int(item.get("score", 0)) >= min_score
            and not item.get("is_form_context")
        ]
        if not typed:
            continue
        best = sorted(typed, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0)))[0]
        result[value_key] = best.get("period_value", "")
        result[evidence_key] = best.get("context") or best.get("raw_text", "")

    deadline_terms = []
    deadline_evidence = []
    seen = set()
    for item in sorted(candidates, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        context = item.get("context", "")
        if item.get("period_type") != "deadline_term":
            continue
        if item.get("is_form_context") or int(item.get("score", 0)) < 40:
            continue
        if not (
            EXTERNAL_DEADLINE_REF_RE.search(context)
            or any(keyword in context for keyword in DEADLINE_TERM_KEYWORDS)
        ):
            continue
        value = item.get("period_value") or item.get("raw_text", "")
        value = re.sub(r"\s+", " ", str(value)).strip()
        if not is_valid_period_value(value, "deadline_term", context):
            continue
        if not value or value in seen:
            continue
        seen.add(value)
        deadline_terms.append(value)
        deadline_evidence.append(context or item.get("raw_text", ""))
        if len(deadline_terms) >= 8:
            break
    result["final_deadline_terms"] = " | ".join(deadline_terms)
    result["final_deadline_terms_evidence"] = " | ".join(deadline_evidence[:5])
    return result

ELIGIBILITY_KEYWORDS = [
    "입찰참가자격", "입찰 참가 자격", "참가자격", "참가 자격", "자격요건", "자격 요건", "입찰참가",
    "공동수급", "공동 수급", "컨소시엄", "대기업", "중소기업", "소기업", "소상공인", "직접생산확인",
    "직접 생산 확인", "소프트웨어사업자", "소프트웨어 사업자", "SW사업자", "정보통신공사업", "실적",
    "수행실적", "인증", "면허", "하도급", "단독", "사업자등록", "입찰참가자격등록", "부정당업자"
]



def score_eligibility_candidate(line: str, context: str, matched_terms: list[str]) -> tuple[int, list[str], bool]:
    haystack = f"{context} {line}"
    score = 0
    reasons = []
    has_heading = any(keyword in haystack for keyword in ["입찰참가자격", "입찰 참가 자격", "참가자격", "참가 자격", "자격요건", "자격 요건"])
    if has_heading:
        score += 30
        reasons.append("eligibility_heading")
    if matched_terms:
        score += min(len(matched_terms) * 7, 42)
        reasons.append("eligibility_terms")
    if any(keyword in haystack for keyword in ["하여야", "제한", "불가", "가능", "등록", "보유", "충족", "이어야", "입찰에 참가"]):
        score += 8
        reasons.append("condition_phrase")
    if len(line) <= 220:
        score += 4
        reasons.append("short_line")
    is_form_context = any(keyword in haystack for keyword in ["별지", "서식", "양식", "작성", "기재"])
    if is_form_context:
        score -= 12
        reasons.append("form_context_candidate_only")
    return score, reasons, is_form_context


def extract_eligibility_candidates(text: str, doc_meta: dict, limit: int = 100) -> list[dict]:
    rows = []
    lines = clean_lines(text)
    for offset, line in enumerate(lines):
        if len(line) > 360 or TOC_DOT_LEADER_RE.search(line):
            continue
        window_start = max(0, offset - 1)
        window_end = min(len(lines), offset + 2)
        context = " ".join(lines[window_start:window_end])
        matched_terms = [term for term in ELIGIBILITY_KEYWORDS if term in context]
        if not matched_terms:
            continue
        score, reasons, is_form_context = score_eligibility_candidate(line, context, matched_terms)
        if score < 18:
            continue
        rows.append({
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "source_file": doc_meta["source_file"],
            "matched_terms": matched_terms,
            "score": score,
            "score_reasons": reasons,
            "is_form_context": is_form_context,
            "line_index": offset + 1,
            "raw_text": line,
            "context": context,
        })
    seen = set()
    unique = []
    for item in sorted(rows, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        key = item["raw_text"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def select_final_eligibility_terms(candidates: list[dict], limit: int = 10, min_score: int = 38) -> list[dict]:
    final_rows = []
    seen = set()
    form_or_submission_hints = [
        "사본", "제출서류", "구비서류", "제출 서류", "등록증", "확인서", "증명서", "서약서",
        "협정서", "확인 자료", "분류 확인 자료", "자료", "1식", "각 1부"
    ]
    condition_hints = ["하여야", "제한", "불가", "가능", "등록되어", "등록된", "등록한", "등록을 필한", "보유", "소지", "충족", "이어야", "입찰에 참가", "참여할 수", "자격"]
    heading_hints = ["입찰참가자격", "입찰 참가 자격", "참가자격", "참가 자격", "자격요건", "자격 요건"]
    for item in sorted(candidates, key=lambda row: (-int(row.get("score", 0)), row.get("line_index", 0))):
        raw_text = re.sub(r"\s+", " ", str(item.get("raw_text", ""))).strip()
        if item.get("is_form_context") or int(item.get("score", 0)) < min_score:
            continue
        line_terms = [term for term in ELIGIBILITY_KEYWORDS if term in raw_text]
        has_heading = any(term in raw_text for term in heading_hints)
        has_condition = any(term in raw_text for term in condition_hints)
        if not line_terms and not has_heading:
            continue
        if any(hint in raw_text for hint in form_or_submission_hints) and not has_heading:
            if not has_condition or "제출" in raw_text:
                continue
        if not raw_text or raw_text in seen:
            continue
        seen.add(raw_text)
        final_rows.append({
            "matched_terms": line_terms or item.get("matched_terms") or [],
            "score": item.get("score", 0),
            "score_reasons": item.get("score_reasons", []),
            "raw_text": raw_text,
            "context": item.get("context", ""),
        })
        if len(final_rows) >= limit:
            break
    return final_rows


def extract_dates(text: str, limit: int = 80) -> list[str]:
    seen = set()
    values = []
    for match in DATE_RE.finditer(text or ""):
        value = re.sub(r"\s+", "", match.group(0))
        if value not in seen:
            seen.add(value)
            values.append(value)
        if len(values) >= limit:
            break
    return values


def extract_amount_strings(text: str, limit: int = 80) -> list[str]:
    seen = set()
    values = []
    for match in AMOUNT_RE.finditer(text or ""):
        value = match.group(0)
        if value not in seen:
            seen.add(value)
            values.append(value)
        if len(values) >= limit:
            break
    return values


def extract_exact_terms(text: str, doc_meta: dict | None = None, limit: int = 120) -> list[str]:
    doc_meta = doc_meta or {}
    terms = []
    for value in [
        doc_meta.get("source_file"),
        doc_meta.get("norm_name"),
        doc_meta.get("project_name"),
        doc_meta.get("issuer"),
        doc_meta.get("final_notice_id") or doc_meta.get("notice_id"),
        doc_meta.get("final_budget") or doc_meta.get("metadata_budget"),
        doc_meta.get("final_budget_krw"),
        doc_meta.get("final_published_at") or doc_meta.get("published_at"),
        doc_meta.get("final_bid_start") or doc_meta.get("bid_start"),
        doc_meta.get("final_bid_deadline") or doc_meta.get("bid_deadline"),
        doc_meta.get("final_project_duration"),
        doc_meta.get("final_maintenance_period"),
        doc_meta.get("final_warranty_period"),
        doc_meta.get("final_deadline_terms"),
        doc_meta.get("final_bid_eligibility_terms"),
    ]:
        if value and str(value).strip():
            terms.append(str(value).strip())

    terms.extend(CODE_RE.findall(text or ""))
    terms.extend(extract_dates(text, limit=30))
    terms.extend(extract_amount_strings(text, limit=30))
    terms.extend(term for term in SUBMISSION_DOC_TERMS if term in (text or ""))
    terms.extend(term for term in ELIGIBILITY_KEYWORDS if term in (text or ""))

    seen = set()
    unique = []
    for term in terms:
        term = re.sub(r"\s+", " ", str(term)).strip()
        if re.fullmatch(r"\d+\.0", term):
            term = term[:-2]
        if not term or term in seen:
            continue
        seen.add(term)
        unique.append(term)
        if len(unique) >= limit:
            break
    return unique


def block_common_metadata(doc_meta: dict) -> dict:
    return {
        "project_name": str(doc_meta.get("project_name") or ""),
        "issuer": str(doc_meta.get("issuer") or ""),
        "notice_id": str(doc_meta.get("notice_id") or ""),
        "external_notice_id": str(doc_meta.get("external_notice_id") or ""),
        "final_notice_id": str(doc_meta.get("final_notice_id") or ""),
        "notice_id_status": str(doc_meta.get("notice_id_status") or ""),
        "notice_id_evidence": str(doc_meta.get("notice_id_evidence") or ""),
        "notice_round": str(doc_meta.get("notice_round") or ""),
        "metadata_budget": str(doc_meta.get("metadata_budget") or ""),
        "final_budget": str(doc_meta.get("final_budget") or ""),
        "final_budget_krw": str(doc_meta.get("final_budget_krw") or ""),
        "final_budget_status": str(doc_meta.get("final_budget_status") or ""),
        "final_budget_evidence": str(doc_meta.get("final_budget_evidence") or ""),
        "published_at": str(doc_meta.get("published_at") or ""),
        "bid_start": str(doc_meta.get("bid_start") or ""),
        "bid_deadline": str(doc_meta.get("bid_deadline") or ""),
        "final_published_at": str(doc_meta.get("final_published_at") or ""),
        "final_bid_start": str(doc_meta.get("final_bid_start") or ""),
        "final_bid_deadline": str(doc_meta.get("final_bid_deadline") or ""),
        "published_at_status": str(doc_meta.get("published_at_status") or ""),
        "bid_start_status": str(doc_meta.get("bid_start_status") or ""),
        "bid_deadline_status": str(doc_meta.get("bid_deadline_status") or ""),
        "published_at_evidence": str(doc_meta.get("published_at_evidence") or ""),
        "bid_start_evidence": str(doc_meta.get("bid_start_evidence") or ""),
        "bid_deadline_evidence": str(doc_meta.get("bid_deadline_evidence") or ""),
        "final_project_duration": str(doc_meta.get("final_project_duration") or ""),
        "final_project_duration_evidence": str(doc_meta.get("final_project_duration_evidence") or ""),
        "final_maintenance_period": str(doc_meta.get("final_maintenance_period") or ""),
        "final_maintenance_period_evidence": str(doc_meta.get("final_maintenance_period_evidence") or ""),
        "final_warranty_period": str(doc_meta.get("final_warranty_period") or ""),
        "final_warranty_period_evidence": str(doc_meta.get("final_warranty_period_evidence") or ""),
        "final_deadline_terms": str(doc_meta.get("final_deadline_terms") or ""),
        "final_deadline_terms_evidence": str(doc_meta.get("final_deadline_terms_evidence") or ""),
        "final_bid_eligibility_terms": str(doc_meta.get("final_bid_eligibility_terms") or ""),
        "final_bid_eligibility_evidence": str(doc_meta.get("final_bid_eligibility_evidence") or ""),
    }


def make_context_header(block: dict) -> str:
    section = " > ".join(block.get("section_path") or [])
    project_name = block.get("project_name") or ""
    issuer = block.get("issuer") or ""
    notice_id = block.get("final_notice_id") or block.get("notice_id") or ""
    parts = [
        f"문서: {block.get('source_file')}",
        f"사업명: {project_name or 'unknown'}",
        f"발주기관: {issuer or 'unknown'}",
    ]
    if notice_id:
        parts.append(f"공고번호: {notice_id}")
    parts.extend([f"섹션: {section or '없음'}", f"유형: {block.get('block_type')}"])
    return "[" + " | ".join(parts) + "]"


def split_text_with_overlap(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            window = text[start + int(max_chars * 0.6): end]
            break_pos = max(window.rfind("\n"), window.rfind(". "), window.rfind("다. "))
            if break_pos > 0:
                end = start + int(max_chars * 0.6) + break_pos + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def blocks_to_chunks(blocks: list[dict], parser_version: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    chunks = []
    for block in blocks:
        text = f"{make_context_header(block)}\n{block.get('text', '')}".strip()
        for part_index, content in enumerate(split_text_with_overlap(text, max_chars=max_chars, overlap=overlap), start=1):
            chunks.append({
                "parser_version": parser_version,
                "chunk_id": f"{block['block_id']}_part_{part_index:03d}",
                "pilot_doc_id": block["pilot_doc_id"],
                "doc_id": block["doc_id"],
                "norm_name": block["norm_name"],
                "source_file": block["source_file"],
                "file_type": block["file_type"],
                "project_name": block.get("project_name", ""),
                "issuer": block.get("issuer", ""),
                "notice_id": block.get("notice_id", ""),
                "external_notice_id": block.get("external_notice_id", ""),
                "final_notice_id": block.get("final_notice_id", ""),
                "notice_id_status": block.get("notice_id_status", ""),
                "notice_id_evidence": block.get("notice_id_evidence", ""),
                "notice_round": block.get("notice_round", ""),
                "metadata_budget": block.get("metadata_budget", ""),
                "final_budget": block.get("final_budget", ""),
                "final_budget_krw": block.get("final_budget_krw", ""),
                "final_budget_status": block.get("final_budget_status", ""),
                "final_budget_evidence": block.get("final_budget_evidence", ""),
                "published_at": block.get("published_at", ""),
                "bid_start": block.get("bid_start", ""),
                "bid_deadline": block.get("bid_deadline", ""),
                "final_published_at": block.get("final_published_at", ""),
                "final_bid_start": block.get("final_bid_start", ""),
                "final_bid_deadline": block.get("final_bid_deadline", ""),
                "published_at_status": block.get("published_at_status", ""),
                "bid_start_status": block.get("bid_start_status", ""),
                "bid_deadline_status": block.get("bid_deadline_status", ""),
                "published_at_evidence": block.get("published_at_evidence", ""),
                "bid_start_evidence": block.get("bid_start_evidence", ""),
                "bid_deadline_evidence": block.get("bid_deadline_evidence", ""),
                "final_project_duration": block.get("final_project_duration", ""),
                "final_project_duration_evidence": block.get("final_project_duration_evidence", ""),
                "final_maintenance_period": block.get("final_maintenance_period", ""),
                "final_maintenance_period_evidence": block.get("final_maintenance_period_evidence", ""),
                "final_warranty_period": block.get("final_warranty_period", ""),
                "final_warranty_period_evidence": block.get("final_warranty_period_evidence", ""),
                "final_deadline_terms": block.get("final_deadline_terms", ""),
                "final_deadline_terms_evidence": block.get("final_deadline_terms_evidence", ""),
                "final_bid_eligibility_terms": block.get("final_bid_eligibility_terms", ""),
                "final_bid_eligibility_evidence": block.get("final_bid_eligibility_evidence", ""),
                "parent_block_id": block["block_id"],
                "chunk_type": block["block_type"],
                "embed_enabled": block["block_type"] != "toc",
                "section_path": block.get("section_path", []),
                "section_type": block.get("section_type", "일반"),
                "content": content,
                "exact_terms": extract_exact_terms(content, block),
                "dates": extract_dates(content),
                "amounts": extract_amount_strings(content),
                "submission_doc_terms": [term for term in SUBMISSION_DOC_TERMS if term in content],
                "chunk_max_chars": max_chars,
                "chunk_overlap": overlap,
                "char_len": len(content),
                "part_index": part_index,
            })
    return chunks


def to_jsonable(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(to_jsonable(record), ensure_ascii=False) + "\n")


def write_summary_markdown(path: Path, summary: dict) -> None:
    lines = [
        "# Parsing Summary",
        "",
        "## Version",
        f"- Output: {summary.get('output_description', 'V1/V2 parsing output')}",
        f"- Output name: {summary.get('parsing_output_name', '')}",
        f"- Version label: {summary.get('parsing_version_label', '')}",
        "",
        "## Counts",
    ]
    for key in [
        "pilot_total_docs", "eval_ground_truth_docs_total", "eval_docs_included", "additional_sampled_docs",
        "eval_physical_source_docs_included", "hwp_docs", "pdf_docs", "parse_success_docs", "parse_failed_docs", "v1_text_blocks",
        "v2_table_blocks", "v1_chunks", "v2_chunks", "docs_with_tables",
        "docs_with_budget_candidates", "docs_with_final_budget", "docs_with_date_candidates", "docs_with_final_bid_deadline", "docs_with_submission_doc_candidates",
        "docs_with_final_submission_documents", "docs_with_notice_id_candidates",
        "docs_with_final_notice_id", "docs_with_rejected_blank_notice_id",
        "docs_with_period_candidates", "docs_with_final_project_duration", "docs_with_final_maintenance_period",
        "docs_with_final_warranty_period", "docs_with_final_deadline_terms",
        "docs_with_eligibility_candidates", "docs_with_final_bid_eligibility_terms",
    ]:
        lines.append(f"- `{key}`: {summary.get(key)}")
    lines.extend([
        "",
        "## Scope",
        "- V1: section/chapter-aware text blocks",
        "- V2: V1 text blocks + table-like row/dict blocks + budget/submission/period/eligibility candidates",
        "- Revision: V1/V2 수정버전, not V3",
        "- Deferred: image OCR, vision embedding, exact page matching",
        "",
        "## Artifact Policy",
        f"- Remove tokens: {', '.join(sorted(ARTIFACT_REMOVE_TOKENS))}",
        f"- Confirmed keep Hanja: {', '.join(sorted(CONFIRMED_KEEP_HANJA_TOKENS))}",
        f"- Keep Hanja runs: {', '.join(sorted(KEEP_HANJA_RUNS))}",
        "",
        "## Chunking",
        f"- Max chars: {CHUNK_MAX_CHARS}",
        f"- Overlap chars: {CHUNK_OVERLAP}",
        "- Retrieval signals: project_name, issuer, notice_id, exact_terms, dates, amounts, submission_doc_terms, period terms, eligibility terms",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def create_metadata_excel(paths: dict[str, Path]) -> Path:
    """Create an Excel workbook for sharing parsing metadata and review candidates."""
    pilot_df = pd.read_csv(paths["pilot_docs_csv"], encoding="utf-8-sig")
    doc_summary_df = pd.read_csv(paths["doc_parse_summary_csv"], encoding="utf-8-sig")
    summary = json.loads(paths["parsing_summary_json"].read_text(encoding="utf-8"))

    text_preview_by_doc = defaultdict(list)
    for block in iter_jsonl(paths["parsed_blocks_v2_jsonl"]):
        if block.get("block_type") == "fact_candidates":
            continue
        doc_id = block.get("doc_id")
        if not doc_id:
            continue
        current_len = sum(len(part) for part in text_preview_by_doc[doc_id])
        if current_len >= 20_000:
            continue
        text_piece = str(block.get("text", "")).strip()
        if text_piece:
            text_preview_by_doc[doc_id].append(text_piece[: max(0, 20_000 - current_len)])

    fact_rows = []
    notice_rows = []
    budget_rows = []
    date_rows = []
    period_rows = []
    eligibility_rows = []
    submission_rows = []
    final_submission_rows = []
    final_eligibility_rows = []
    for block in iter_jsonl(paths["parsed_blocks_v2_jsonl"]):
        if block.get("block_type") != "fact_candidates":
            continue
        structured = block.get("structured_data") or {}
        for item in structured.get("notice_id_candidates") or []:
            row = dict(item)
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            notice_rows.append(row)
        for item in structured.get("budget_candidates") or []:
            row = dict(item)
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            budget_rows.append(row)
        for item in structured.get("date_candidates") or []:
            row = dict(item)
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            date_rows.append(row)
        for item in structured.get("period_candidates") or []:
            row = dict(item)
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            period_rows.append(row)
        for item in structured.get("eligibility_candidates") or []:
            row = dict(item)
            row["matched_terms"] = ", ".join(row.get("matched_terms") or [])
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            eligibility_rows.append(row)
        for item in structured.get("submission_document_candidates") or []:
            row = dict(item)
            row["name_candidates"] = ", ".join(row.get("name_candidates") or [])
            row["normalized_names"] = ", ".join(row.get("normalized_names") or [])
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            submission_rows.append(row)
        for item in structured.get("final_submission_documents") or []:
            row = dict(item)
            row["pilot_doc_id"] = block.get("pilot_doc_id")
            row["doc_id"] = block.get("doc_id")
            row["source_file"] = block.get("source_file")
            row["name_candidates"] = ", ".join(row.get("name_candidates") or [])
            row["normalized_names"] = ", ".join(row.get("normalized_names") or [])
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            final_submission_rows.append(row)
        for item in structured.get("final_bid_eligibility_items") or []:
            row = dict(item)
            row["pilot_doc_id"] = block.get("pilot_doc_id")
            row["doc_id"] = block.get("doc_id")
            row["source_file"] = block.get("source_file")
            row["matched_terms"] = ", ".join(row.get("matched_terms") or [])
            row["score_reasons"] = ", ".join(row.get("score_reasons") or [])
            final_eligibility_rows.append(row)
        fact_rows.append({
            "pilot_doc_id": block.get("pilot_doc_id"),
            "doc_id": block.get("doc_id"),
            "source_file": block.get("source_file"),
            "final_notice_id": structured.get("final_notice_id", ""),
            "notice_id_status": structured.get("notice_id_status", ""),
            "notice_id_evidence": structured.get("notice_id_evidence", ""),
            "notice_id_rejected_blank_count": structured.get("notice_id_rejected_blank_count", 0),
            "notice_id_candidate_count": len(structured.get("notice_id_candidates") or []),
            "final_budget": structured.get("final_budget", ""),
            "final_budget_krw": structured.get("final_budget_krw", ""),
            "final_budget_status": structured.get("final_budget_status", ""),
            "final_budget_evidence": structured.get("final_budget_evidence", ""),
            "budget_candidate_count": len(structured.get("budget_candidates") or []),
            "final_published_at": structured.get("final_published_at", ""),
            "final_bid_start": structured.get("final_bid_start", ""),
            "final_bid_deadline": structured.get("final_bid_deadline", ""),
            "published_at_status": structured.get("published_at_status", ""),
            "bid_start_status": structured.get("bid_start_status", ""),
            "bid_deadline_status": structured.get("bid_deadline_status", ""),
            "published_at_evidence": structured.get("published_at_evidence", ""),
            "bid_start_evidence": structured.get("bid_start_evidence", ""),
            "bid_deadline_evidence": structured.get("bid_deadline_evidence", ""),
            "date_candidate_count": len(structured.get("date_candidates") or []),
            "period_candidate_count": len(structured.get("period_candidates") or []),
            "final_project_duration": structured.get("final_project_duration", ""),
            "final_project_duration_evidence": structured.get("final_project_duration_evidence", ""),
            "final_maintenance_period": structured.get("final_maintenance_period", ""),
            "final_maintenance_period_evidence": structured.get("final_maintenance_period_evidence", ""),
            "final_warranty_period": structured.get("final_warranty_period", ""),
            "final_warranty_period_evidence": structured.get("final_warranty_period_evidence", ""),
            "final_deadline_terms": structured.get("final_deadline_terms", ""),
            "final_deadline_terms_evidence": structured.get("final_deadline_terms_evidence", ""),
            "eligibility_candidate_count": len(structured.get("eligibility_candidates") or []),
            "final_bid_eligibility_terms": structured.get("final_bid_eligibility_terms", ""),
            "final_bid_eligibility_evidence": structured.get("final_bid_eligibility_evidence", ""),
            "final_bid_eligibility_term_count": len(structured.get("final_bid_eligibility_items") or []),
            "submission_doc_candidate_count": len(structured.get("submission_document_candidates") or []),
            "final_submission_doc_count": len(structured.get("final_submission_documents") or []),
            "final_submission_documents_text": structured.get("final_submission_documents_text", ""),
            "final_submission_document_groups_text": structured.get("final_submission_document_groups_text", ""),
            "final_submission_document_name_count": len(structured.get("final_submission_document_names") or []),
        })

    metadata_df = pilot_df.merge(
        doc_summary_df,
        on=["pilot_doc_id", "doc_id", "norm_name", "source_file", "file_type", "is_eval_ground_truth"],
        how="left",
    )
    fact_count_df = pd.DataFrame(fact_rows)
    if not fact_count_df.empty:
        metadata_df = metadata_df.merge(
            fact_count_df,
            on=["pilot_doc_id", "doc_id", "source_file"],
            how="left",
            suffixes=("", "_fact"),
        )

    metadata_df["원문텍스트_20000자"] = metadata_df["doc_id"].map(
        lambda doc_id: "\n\n".join(text_preview_by_doc.get(doc_id, []))[:20_000]
    ).fillna("")
    inferred_titles = metadata_df.apply(
        lambda row: infer_doc_title_fields(row.get("source_file", ""), row.get("norm_name", "")),
        axis=1,
    )
    metadata_df["issuer_from_filename"] = [item[0] for item in inferred_titles]
    metadata_df["project_name_from_filename"] = [item[1] for item in inferred_titles]

    def col(name: str, default="") -> pd.Series:
        if name in metadata_df.columns:
            return metadata_df[name].fillna(default)
        return pd.Series([default] * len(metadata_df))

    export_df = pd.DataFrame({
        "공고 번호": col("final_notice_id"),
        "사업명": metadata_df["project_name_from_filename"],
        "사업 금액": col("final_budget"),
        "사업금액_원": col("final_budget_krw"),
        "사업금액_상태": col("final_budget_status"),
        "사업금액_근거": col("final_budget_evidence"),
        "사업기간": col("final_project_duration"),
        "사업기간_근거": col("final_project_duration_evidence"),
        "무상유지보수기간": col("final_maintenance_period"),
        "무상유지보수기간_근거": col("final_maintenance_period_evidence"),
        "하자담보책임기간": col("final_warranty_period"),
        "하자담보책임기간_근거": col("final_warranty_period_evidence"),
        "기한/기간 기타": col("final_deadline_terms"),
        "기한/기간 기타_근거": col("final_deadline_terms_evidence"),
        "입찰참가자격": col("final_bid_eligibility_terms"),
        "입찰참가자격_근거": col("final_bid_eligibility_evidence"),
        "발주 기관": metadata_df["issuer_from_filename"],
        "공개 일자": col("final_published_at"),
        "입찰 참여 시작일": col("final_bid_start"),
        "입찰 참여 마감일": col("final_bid_deadline"),
        "공개일자_근거": col("published_at_evidence"),
        "입찰시작일_근거": col("bid_start_evidence"),
        "입찰마감일_근거": col("bid_deadline_evidence"),
        "제출서류": col("final_submission_documents_text"),
        "제출서류_근거묶음": col("final_submission_document_groups_text"),
        "사업 요약": col("원문텍스트_20000자").astype(str).str[:1200],
        "원문텍스트_20000자": col("원문텍스트_20000자"),
        "파일형식": col("file_type"),
        "파일명": col("source_file"),
        "pilot_doc_id": col("pilot_doc_id"),
        "doc_id": col("doc_id"),
        "is_eval_ground_truth": col("is_eval_ground_truth"),
        "sampling_reason": col("sampling_reason"),
        "parser_status": col("parser_status"),
        "raw_char_len": col("raw_char_len"),
        "clean_char_len": col("clean_char_len"),
        "v1_text_blocks": col("v1_text_blocks"),
        "v2_table_blocks": col("v2_table_blocks"),
        "v1_chunks": col("v1_chunks"),
        "v2_chunks": col("v2_chunks"),
        "budget_candidate_count": col("budget_candidate_count"),
        "date_candidate_count": col("date_candidate_count"),
        "period_candidate_count": col("period_candidate_count"),
        "eligibility_candidate_count": col("eligibility_candidate_count"),
        "submission_doc_candidate_count": col("submission_doc_candidate_count"),
        "final_submission_doc_count": col("final_submission_doc_count"),
        "final_submission_document_name_count": col("final_submission_document_name_count"),
        "source_path": col("source_path"),
    })

    summary_df = pd.DataFrame([{"key": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value} for key, value in summary.items()])
    notice_df = pd.DataFrame(notice_rows)
    budget_df = pd.DataFrame(budget_rows)
    date_df = pd.DataFrame(date_rows)
    period_df = pd.DataFrame(period_rows)
    eligibility_df = pd.DataFrame(eligibility_rows)
    submission_df = pd.DataFrame(submission_rows)
    final_submission_df = pd.DataFrame(final_submission_rows)
    final_eligibility_df = pd.DataFrame(final_eligibility_rows)

    with pd.ExcelWriter(paths["metadata_excel"], engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="metadata_250")
        summary_df.to_excel(writer, index=False, sheet_name="summary")
        doc_summary_df.to_excel(writer, index=False, sheet_name="doc_parse_summary")
        notice_df.to_excel(writer, index=False, sheet_name="notice_id_candidates")
        budget_df.to_excel(writer, index=False, sheet_name="budget_candidates")
        date_df.to_excel(writer, index=False, sheet_name="date_candidates")
        period_df.to_excel(writer, index=False, sheet_name="period_candidates")
        eligibility_df.to_excel(writer, index=False, sheet_name="eligibility_candidates")
        submission_df.to_excel(writer, index=False, sheet_name="submission_candidates")
        final_submission_df.to_excel(writer, index=False, sheet_name="final_submission_docs")
        final_eligibility_df.to_excel(writer, index=False, sheet_name="final_eligibility_terms")

    return paths["metadata_excel"]



TOC_TITLE_RE = re.compile(r"^\s*(목\s*차|차\s*례|CONTENTS?)\s*$", re.I)
TOC_ENTRY_RE = re.compile(
    r"^\s*((제\s*\d+\s*[장절관항])|([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.．]?)|(\d+\s*[.)])|([가-하]\s*[.)]))\s*"
    r".{1,80}?\s+\d{1,3}\s*$"
)
UNIT_BLACKLIST_RE = re.compile(r"\d+\s*(부|매|식|개|개월|년|일|원|억원|천원|만원|%|점|명|건|회)\s*$")


def strip_toc_trailing_page_number(line: str) -> str:
    """Remove only the final page number from a likely TOC entry line."""
    line = normalize_line(line)
    if not line:
        return line
    if UNIT_BLACKLIST_RE.search(line):
        return line
    if not TOC_ENTRY_RE.search(line):
        return line
    return re.sub(r"\s+\d{1,3}\s*$", "", line).strip()


def analyze_pdf_toc(pdf_path: str | Path, max_pages: int = 12) -> dict:
    pdf_path = Path(pdf_path)
    result = {
        "source_file": pdf_path.name,
        "source_path": str(pdf_path),
        "page_count": 0,
        "has_toc": False,
        "toc_start_page": None,
        "toc_end_page": None,
        "toc_title_pages": [],
        "toc_entry_count": 0,
        "toc_entry_pages": [],
        "toc_sample_before": "",
        "toc_sample_after": "",
        "error": "",
    }
    try:
        reader = PdfReader(str(pdf_path))
        result["page_count"] = len(reader.pages)
        page_limit = min(len(reader.pages), max_pages)
        samples_before = []
        samples_after = []
        entry_pages = []
        title_pages = []

        for page_index in range(page_limit):
            text = reader.pages[page_index].extract_text() or ""
            lines = clean_lines(text)
            page_no = page_index + 1
            if any(TOC_TITLE_RE.search(line) for line in lines):
                title_pages.append(page_no)
            page_entry_count = 0
            for line in lines:
                if UNIT_BLACKLIST_RE.search(line):
                    continue
                if TOC_ENTRY_RE.search(line):
                    page_entry_count += 1
                    if len(samples_before) < 8:
                        samples_before.append(line)
                        samples_after.append(strip_toc_trailing_page_number(line))
            if page_entry_count:
                entry_pages.append(page_no)
                result["toc_entry_count"] += page_entry_count

        result["toc_title_pages"] = title_pages
        result["toc_entry_pages"] = entry_pages
        result["has_toc"] = bool(title_pages or result["toc_entry_count"] >= 3)
        if result["has_toc"]:
            candidates = title_pages or entry_pages
            result["toc_start_page"] = min(candidates) if candidates else None
            result["toc_end_page"] = max(entry_pages or candidates) if candidates else None
        result["toc_sample_before"] = " || ".join(samples_before)
        result["toc_sample_after"] = " || ".join(samples_after)
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def build_pdf_toc_report(pdf_dir: str | Path, output_csv: str | Path, max_pages: int = 12) -> pd.DataFrame:
    pdf_dir = Path(pdf_dir)
    output_csv = Path(output_csv)
    rows = [analyze_pdf_toc(path, max_pages=max_pages) for path in tqdm(sorted(pdf_dir.glob("*.pdf")), desc="analyze pdf toc")]
    df = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return df


def run_parsing_pipeline(paths: dict[str, Path], pilot_docs_df: pd.DataFrame | None = None) -> tuple[dict, pd.DataFrame]:
    if pilot_docs_df is None:
        pilot_docs_df = pd.read_csv(paths["pilot_docs_csv"], encoding="utf-8-sig")
    assert len(pilot_docs_df) == PILOT_TOTAL_DOCS
    assert int(pilot_docs_df["is_eval_ground_truth"].astype(bool).sum()) == EVAL_PHYSICAL_SOURCE_DOCS_TOTAL

    parsed_blocks_v1 = []
    parsed_blocks_v2 = []
    chunks_v1 = []
    chunks_v2 = []
    doc_summary_rows = []

    for _, doc_row in tqdm(pilot_docs_df.iterrows(), total=len(pilot_docs_df), desc="parse pilot docs"):
        doc_meta = sanitize_doc_meta_for_db(doc_row.to_dict())
        extracted = extract_document_text(doc_meta["source_path"])
        doc_summary = {
            "pilot_doc_id": doc_meta["pilot_doc_id"],
            "doc_id": doc_meta["doc_id"],
            "norm_name": doc_meta["norm_name"],
            "source_file": doc_meta["source_file"],
            "file_type": doc_meta["file_type"],
            "is_eval_ground_truth": bool(doc_meta["is_eval_ground_truth"]),
            "parser_status": extracted["parser_status"],
            "parser": extracted["parser"],
            "raw_char_len": extracted["raw_char_len"],
            "clean_char_len": extracted["clean_char_len"],
            "error": extracted["error"],
            "v1_text_blocks": 0,
            "v2_table_blocks": 0,
            "v1_chunks": 0,
            "v2_chunks": 0,
            "budget_candidate_count": 0,
            "date_candidate_count": 0,
            "period_candidate_count": 0,
            "eligibility_candidate_count": 0,
            "final_bid_eligibility_term_count": 0,
            "submission_doc_candidate_count": 0,
            "final_submission_doc_count": 0,
            "notice_id_candidate_count": 0,
            "notice_id_rejected_blank_count": 0,
            "final_notice_id": "",
            "notice_id_status": "missing",
            "final_budget": "",
            "final_budget_krw": "",
            "final_budget_status": "missing",
            "final_published_at": "",
            "final_bid_start": "",
            "final_bid_deadline": "",
            "final_project_duration": "",
            "final_maintenance_period": "",
            "final_warranty_period": "",
            "final_deadline_terms": "",
            "final_bid_eligibility_terms": "",
        }
        if extracted["parser_status"] != "success" or not extracted["clean_text"].strip():
            doc_summary_rows.append(doc_summary)
            continue

        clean_text = extracted["clean_text"]
        notice_summary = extract_notice_id_summary(clean_text, doc_meta)
        doc_meta.update({
            "notice_id": notice_summary["final_notice_id"],
            "final_notice_id": notice_summary["final_notice_id"],
            "notice_id_status": notice_summary["notice_id_status"],
            "notice_id_evidence": notice_summary["notice_id_evidence"],
        })
        budget_candidates = extract_budget_candidates(clean_text, doc_meta)
        budget_summary = select_final_budget(budget_candidates)
        date_candidates = extract_date_candidates(clean_text, doc_meta)
        date_summary = select_final_dates(date_candidates)
        period_candidates = extract_period_candidates(clean_text, doc_meta)
        period_summary = select_final_periods(period_candidates)
        eligibility_candidates = extract_eligibility_candidates(clean_text, doc_meta)
        final_eligibility_items = select_final_eligibility_terms(eligibility_candidates)
        eligibility_summary = {
            "final_bid_eligibility_terms": " | ".join(item.get("raw_text", "") for item in final_eligibility_items),
            "final_bid_eligibility_evidence": " | ".join(item.get("context", "") for item in final_eligibility_items[:5]),
        }
        doc_meta.update(budget_summary)
        doc_meta.update(date_summary)
        doc_meta.update(period_summary)
        doc_meta.update(eligibility_summary)
        doc_meta["metadata_budget"] = budget_summary.get("final_budget", "")
        doc_meta["published_at"] = date_summary.get("final_published_at", "")
        doc_meta["bid_start"] = date_summary.get("final_bid_start", "")
        doc_meta["bid_deadline"] = date_summary.get("final_bid_deadline", "")

        v1_blocks = build_v1_blocks(doc_meta, clean_text)
        v2_table_blocks = build_v2_table_blocks(doc_meta, clean_text)
        submission_candidates = extract_submission_doc_candidates(clean_text, doc_meta)
        final_submission_documents = select_final_submission_documents(submission_candidates)
        final_submission_document_names = flatten_final_submission_document_names(final_submission_documents)
        final_submission_documents_text = ", ".join(final_submission_document_names)
        final_submission_document_groups_text = build_submission_group_text(final_submission_documents)
        v2_blocks = [
            {**block, "parser_version": "v2_table_aware", "block_id": block["block_id"].replace("_v1_", "_v2_")}
            for block in v1_blocks
        ] + v2_table_blocks

        v1_doc_chunks = blocks_to_chunks(v1_blocks, parser_version="v1")
        v2_doc_chunks = blocks_to_chunks(v2_blocks, parser_version="v2")

        has_fact_candidates = any([
            budget_candidates,
            date_candidates,
            period_candidates,
            eligibility_candidates,
            submission_candidates,
            notice_summary["notice_id_candidates"],
        ])
        if has_fact_candidates:
            fact_text_lines = [
                *[f"공고번호 후보: {item['notice_id']} / {item['raw_text']}" for item in notice_summary["notice_id_candidates"][:10]],
                *[f"예산 후보: {item['raw_amount']} / {item['context']}" for item in budget_candidates[:10]],
                f"최종 예산: {budget_summary.get('final_budget', '')} / {budget_summary.get('final_budget_evidence', '')}" if budget_summary.get("final_budget") else "",
                *[f"일자 후보: {item['date_type']} {item['normalized_datetime']} / {item['raw_text']}" for item in date_candidates[:20]],
                *[f"기간/기한 후보: {item['period_type']} {item.get('period_value', '')} / {item['raw_text']}" for item in period_candidates[:20]],
                f"최종 사업기간: {period_summary.get('final_project_duration', '')} / {period_summary.get('final_project_duration_evidence', '')}" if period_summary.get("final_project_duration") else "",
                f"최종 무상유지보수기간: {period_summary.get('final_maintenance_period', '')} / {period_summary.get('final_maintenance_period_evidence', '')}" if period_summary.get("final_maintenance_period") else "",
                f"최종 하자담보책임기간: {period_summary.get('final_warranty_period', '')} / {period_summary.get('final_warranty_period_evidence', '')}" if period_summary.get("final_warranty_period") else "",
                f"최종 기한/기간 기타: {period_summary.get('final_deadline_terms', '')} / {period_summary.get('final_deadline_terms_evidence', '')}" if period_summary.get("final_deadline_terms") else "",
                *[f"입찰참가자격 후보: {', '.join(item.get('matched_terms') or [])} / {item['raw_text']}" for item in eligibility_candidates[:20]],
                *[f"최종 입찰참가자격: {', '.join(item.get('matched_terms') or [])} / {item['raw_text']}" for item in final_eligibility_items[:10]],
                *[f"제출서류 후보: {', '.join(item.get('normalized_names') or item.get('name_candidates') or [])} / {item['raw_text']}" for item in submission_candidates[:20]],
                *[f"최종 제출서류 묶음: {', '.join(item.get('normalized_names') or item.get('name_candidates') or [])} / {item['raw_text']}" for item in final_submission_documents[:20]],
            ]
            fact_text = "\n".join(line for line in fact_text_lines if line)
            fact_block = {
                "parser_version": "v2_table_aware",
                "pilot_doc_id": doc_meta["pilot_doc_id"],
                "doc_id": doc_meta["doc_id"],
                "norm_name": doc_meta["norm_name"],
                "source_file": doc_meta["source_file"],
                "file_type": doc_meta["file_type"],
                **block_common_metadata(doc_meta),
                "block_id": f"{doc_meta['pilot_doc_id']}_v2_fact_0001",
                "block_type": "fact_candidates",
                "section_path": ["문서 전체"],
                "section_type": "추출필드후보",
                "text": fact_text,
                "structured_data": {
                    "notice_id_candidates": notice_summary["notice_id_candidates"],
                    "final_notice_id": notice_summary["final_notice_id"],
                    "notice_id_status": notice_summary["notice_id_status"],
                    "notice_id_evidence": notice_summary["notice_id_evidence"],
                    "notice_id_rejected_blank_count": notice_summary["notice_id_rejected_blank_count"],
                    "budget_candidates": budget_candidates,
                    **budget_summary,
                    "date_candidates": date_candidates,
                    **date_summary,
                    "period_candidates": period_candidates,
                    **period_summary,
                    "eligibility_candidates": eligibility_candidates,
                    "final_bid_eligibility_items": final_eligibility_items,
                    **eligibility_summary,
                    "submission_document_candidates": submission_candidates,
                    "final_submission_documents": final_submission_documents,
                    "final_submission_documents_text": final_submission_documents_text,
                    "final_submission_document_groups_text": final_submission_document_groups_text,
                    "final_submission_document_names": final_submission_document_names,
                },
                "exact_terms": extract_exact_terms(fact_text, doc_meta),
                "dates": extract_dates(fact_text),
                "amounts": extract_amount_strings(fact_text),
                "char_len": len(fact_text),
            }
            v2_blocks.append(fact_block)
            v2_doc_chunks.extend(blocks_to_chunks([fact_block], parser_version="v2"))

        parsed_blocks_v1.extend(v1_blocks)
        parsed_blocks_v2.extend(v2_blocks)
        chunks_v1.extend(v1_doc_chunks)
        chunks_v2.extend(v2_doc_chunks)

        doc_summary.update({
            "v1_text_blocks": len(v1_blocks),
            "v2_table_blocks": len(v2_table_blocks),
            "v1_chunks": len(v1_doc_chunks),
            "v2_chunks": len(v2_doc_chunks),
            "budget_candidate_count": len(budget_candidates),
            "date_candidate_count": len(date_candidates),
            "period_candidate_count": len(period_candidates),
            "eligibility_candidate_count": len(eligibility_candidates),
            "final_bid_eligibility_term_count": len(final_eligibility_items),
            "submission_doc_candidate_count": len(submission_candidates),
            "final_submission_doc_count": len(final_submission_documents),
            "notice_id_candidate_count": len(notice_summary["notice_id_candidates"]),
            "notice_id_rejected_blank_count": notice_summary["notice_id_rejected_blank_count"],
            "final_notice_id": notice_summary["final_notice_id"],
            "notice_id_status": notice_summary["notice_id_status"],
            "final_budget": budget_summary.get("final_budget", ""),
            "final_budget_krw": budget_summary.get("final_budget_krw", ""),
            "final_budget_status": budget_summary.get("final_budget_status", ""),
            "final_published_at": date_summary.get("final_published_at", ""),
            "final_bid_start": date_summary.get("final_bid_start", ""),
            "final_bid_deadline": date_summary.get("final_bid_deadline", ""),
            "final_project_duration": period_summary.get("final_project_duration", ""),
            "final_maintenance_period": period_summary.get("final_maintenance_period", ""),
            "final_warranty_period": period_summary.get("final_warranty_period", ""),
            "final_deadline_terms": period_summary.get("final_deadline_terms", ""),
            "final_bid_eligibility_terms": eligibility_summary.get("final_bid_eligibility_terms", ""),
        })
        doc_summary_rows.append(doc_summary)

    write_jsonl(paths["parsed_blocks_v1_jsonl"], parsed_blocks_v1)
    write_jsonl(paths["parsed_blocks_v2_jsonl"], parsed_blocks_v2)
    write_jsonl(paths["chunks_v1_jsonl"], chunks_v1)
    write_jsonl(paths["chunks_v2_jsonl"], chunks_v2)

    doc_summary_df = pd.DataFrame(doc_summary_rows)
    doc_summary_df.to_csv(paths["doc_parse_summary_csv"], index=False, encoding="utf-8-sig")

    summary = {
        "output_description": paths.get("output_description", "V1/V2 parsing output"),
        "parsing_output_name": paths.get("parsing_output_name", ""),
        "parsing_version_label": paths.get("parsing_version_label", ""),
        "pilot_total_docs": int(len(pilot_docs_df)),
        "eval_ground_truth_docs_total": EVAL_GROUND_TRUTH_DOCS_TOTAL,
        "eval_docs_included": EVAL_GROUND_TRUTH_DOCS_TOTAL,
        "eval_physical_source_docs_included": int(pilot_docs_df["is_eval_ground_truth"].astype(bool).sum()),
        "additional_sampled_docs": int((~pilot_docs_df["is_eval_ground_truth"].astype(bool)).sum()),
        "hwp_docs": int((pilot_docs_df["file_type"] == "hwp").sum()),
        "pdf_docs": int((pilot_docs_df["file_type"] == "pdf").sum()),
        "parse_success_docs": int((doc_summary_df["parser_status"] == "success").sum()),
        "parse_failed_docs": int((doc_summary_df["parser_status"] != "success").sum()),
        "v1_text_blocks": int(len(parsed_blocks_v1)),
        "v2_table_blocks": int(sum(1 for block in parsed_blocks_v2 if block.get("block_type") == "table")),
        "v1_chunks": int(len(chunks_v1)),
        "v2_chunks": int(len(chunks_v2)),
        "docs_with_tables": int((doc_summary_df["v2_table_blocks"] > 0).sum()),
        "docs_with_budget_candidates": int((doc_summary_df["budget_candidate_count"] > 0).sum()),
        "docs_with_final_budget": int((doc_summary_df["final_budget"].astype(str).str.strip() != "").sum()),
        "docs_with_date_candidates": int((doc_summary_df["date_candidate_count"] > 0).sum()),
        "docs_with_final_bid_deadline": int((doc_summary_df["final_bid_deadline"].astype(str).str.strip() != "").sum()),
        "docs_with_period_candidates": int((doc_summary_df["period_candidate_count"] > 0).sum()),
        "docs_with_final_project_duration": int((doc_summary_df["final_project_duration"].astype(str).str.strip() != "").sum()),
        "docs_with_final_maintenance_period": int((doc_summary_df["final_maintenance_period"].astype(str).str.strip() != "").sum()),
        "docs_with_final_warranty_period": int((doc_summary_df["final_warranty_period"].astype(str).str.strip() != "").sum()),
        "docs_with_final_deadline_terms": int((doc_summary_df["final_deadline_terms"].astype(str).str.strip() != "").sum()),
        "docs_with_eligibility_candidates": int((doc_summary_df["eligibility_candidate_count"] > 0).sum()),
        "docs_with_final_bid_eligibility_terms": int((doc_summary_df["final_bid_eligibility_terms"].astype(str).str.strip() != "").sum()),
        "docs_with_submission_doc_candidates": int((doc_summary_df["submission_doc_candidate_count"] > 0).sum()),
        "docs_with_final_submission_documents": int((doc_summary_df["final_submission_doc_count"] > 0).sum()),
        "docs_with_notice_id_candidates": int((doc_summary_df["notice_id_candidate_count"] > 0).sum()),
        "docs_with_final_notice_id": int((doc_summary_df["final_notice_id"].astype(str).str.strip() != "").sum()),
        "docs_with_rejected_blank_notice_id": int((doc_summary_df["notice_id_rejected_blank_count"] > 0).sum()),
        "notice_id_status_counts": doc_summary_df["notice_id_status"].value_counts(dropna=False).to_dict(),
        "budget_status_counts": doc_summary_df["final_budget_status"].value_counts(dropna=False).to_dict(),
        "artifact_remove_tokens": sorted(ARTIFACT_REMOVE_TOKENS),
        "confirmed_keep_hanja_tokens": sorted(CONFIRMED_KEEP_HANJA_TOKENS),
        "keep_hanja_runs": sorted(KEEP_HANJA_RUNS),
        "chunk_max_chars": CHUNK_MAX_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
    }

    paths["parsing_summary_json"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_markdown(paths["parsing_summary_md"], summary)
    return summary, doc_summary_df

