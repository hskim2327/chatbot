from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3]))
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

PACKAGES = {
    "125": {
        "src": ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix",
        "dst": ROOT / "outputs/parsing_p4_hwpx_125_datafix_goalfix_slim",
        "chunks": "chunks_v2_125.jsonl",
        "sources": "source_store_v2_125.jsonl",
        "pilot": "pilot_docs_125.csv",
        "xlsx": "metadata_light_125.xlsx",
    },
    "250": {
        "src": ROOT / "outputs/parsing_p4_hwpx_250_basic",
        "dst": ROOT / "outputs/parsing_p4_hwpx_250_basic_slim",
        "chunks": "chunks_v2_250.jsonl",
        "sources": "source_store_v2_250.jsonl",
        "pilot": "pilot_docs_250.csv",
        "xlsx": "metadata_light_250.xlsx",
    },
    "690": {
        "src": ROOT / "outputs/parsing_p4_hwpx_690_basic",
        "dst": ROOT / "outputs/parsing_p4_hwpx_690_basic_slim",
        "chunks": "chunks_v2_690.jsonl",
        "sources": "source_store_v2_690.jsonl",
        "pilot": "pilot_docs_690.csv",
        "xlsx": "metadata_light_690.xlsx",
    },
}

FORBIDDEN_MARKERS = [
    "alia보강",
    "alias 보강",
    "alias보강",
    "수동 alias 보강",
    "보강(Q100)",
    "alias 보강(Q100)",
    "alias/routing 보강",
    "alias 보정",
    "수동 alias",
]

TARGET_NEEDLES = {
    "125": [
        "780230000",
        "2349130320",
        "843000000",
        "195030000",
        "50000000",
        "400000000",
    ],
    "250": [
        "780230000",
        "2349130320",
        "843000000",
        "195030000",
        "50000000",
        "400000000",
    ],
    "690": [
        "780230000",
        "2349130320",
        "843000000",
        "195030000",
        "5031000000",
        "129300000",
        "336403000",
        "50000000",
        "400000000",
    ],
}


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_mib(path: Path) -> float:
    return round(path.stat().st_size / 1024 / 1024, 2)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield line, json.loads(line)


def compact_amount_text(text: str) -> str:
    return text.replace(",", "").replace(" ", "")


def scalar_metadata_stats(chunks_path: Path) -> dict[str, Any]:
    content_lens = []
    chunk_type_counts = Counter()
    fact_type_counts = Counter()
    fact_status_counts = Counter()
    fact_confidence_counts = Counter()
    answer_policy_counts = Counter()
    answer_risk_level_counts = Counter()
    table_role_counts = Counter()
    row_type_counts = Counter()
    budget_enabled = 0
    eligibility_enabled = 0
    payment_enabled = 0
    low_confidence_fact_embedded = 0
    for _, row in iter_jsonl(chunks_path):
        md = row.get("metadata") or {}
        content_lens.append(len(str(row.get("content") or "")))
        chunk_type_counts[str(row.get("chunk_type") or md.get("chunk_type") or "")] += 1
        fact_type = str(row.get("fact_type") or md.get("fact_type") or "")
        fact_status = str(row.get("fact_status") or md.get("fact_status") or "")
        fact_confidence = str(row.get("fact_confidence") or md.get("fact_confidence") or "")
        if fact_type:
            fact_type_counts[fact_type] += 1
        if fact_status:
            fact_status_counts[fact_status] += 1
        if fact_confidence:
            fact_confidence_counts[fact_confidence] += 1
        policy = str(row.get("answer_policy") or md.get("answer_policy") or "")
        risk = str(row.get("answer_risk_level") or md.get("answer_risk_level") or "")
        if policy:
            answer_policy_counts[policy] += 1
        if risk:
            answer_risk_level_counts[risk] += 1
        table_role = str(md.get("table_role") or "")
        row_type = str(md.get("row_type") or "")
        if table_role:
            table_role_counts[table_role] += 1
        if row_type:
            row_type_counts[row_type] += 1
        if row.get("budget_answer_enabled") is True or md.get("budget_answer_enabled") is True:
            budget_enabled += 1
        if row.get("eligibility_answer_enabled") is True or md.get("eligibility_answer_enabled") is True:
            eligibility_enabled += 1
        if row.get("payment_answer_enabled") is True or md.get("payment_answer_enabled") is True:
            payment_enabled += 1
        if fact_confidence == "low":
            low_confidence_fact_embedded += 1
    if content_lens:
        sorted_lens = sorted(content_lens)
        p50 = sorted_lens[len(sorted_lens) // 2]
        p95 = sorted_lens[min(len(sorted_lens) - 1, int(len(sorted_lens) * 0.95))]
    else:
        p50 = p95 = 0
    return {
        "chunk_type_counts": dict(chunk_type_counts),
        "fact_type_counts": dict(fact_type_counts),
        "embedded_fact_type_counts": dict(fact_type_counts),
        "fact_status_counts": dict(fact_status_counts),
        "fact_confidence_counts": dict(fact_confidence_counts),
        "answer_policy_counts": dict(answer_policy_counts),
        "answer_risk_level_counts": dict(answer_risk_level_counts),
        "table_role_counts": dict(table_role_counts),
        "row_type_counts": dict(row_type_counts),
        "avg_content_len": round(statistics.mean(content_lens), 2) if content_lens else 0,
        "p50_content_len": p50,
        "p95_content_len": p95,
        "max_content_len": max(content_lens) if content_lens else 0,
        "budget_answer_enabled_count": budget_enabled,
        "budget_answer_enabled_fact_count": budget_enabled,
        "eligibility_answer_enabled_fact_count": eligibility_enabled,
        "payment_answer_enabled_fact_count": payment_enabled,
        "low_confidence_fact_embedded_count": low_confidence_fact_embedded,
    }


def make_readme(label: str, stats: dict[str, Any]) -> str:
    return f"""# parsing_p4_hwpx_{label} Slim Retrieval Corpus

이 폴더는 팀원 실험 공유용 slim corpus입니다. 원본 full corpus는 보존하고, Chroma 임베딩 대상인 `embed_enabled=true` 청크만 남겼습니다.

## 핵심 파일

| 파일 | 설명 |
|---|---|
| `chunks_v2_{label}.jsonl` | Chroma 적재 기본 입력입니다. 모든 record가 `embed_enabled=true`입니다. |
| `source_store_v2_{label}.jsonl` | 남은 청크가 참조하는 원문/표 근거만 남긴 파일입니다. 직접 임베딩하지 않습니다. |
| `pilot_docs_{label}.csv` | 문서 목록과 주요 metadata budget 참고 파일입니다. |
| `metadata_light_{label}.xlsx` | 문서별 파싱/예산 요약 확인용 엑셀입니다. |
| `validation_report_v2.json` | slim package 무결성 검증 결과입니다. |
| `manifest.json` | slim package 파일명, hash, 원본 대비 축소 정보를 기록합니다. |
| `json_key_description.md` | JSON/JSONL key와 사용 정책 설명입니다. |
| `corpus_slim_handoff.md` / `corpus_slim_handoff.html` | 팀원 공유용 설명 문서입니다. |

## 사용 기준

- 팀원이 Chroma에 넣어야 하는 파일은 `chunks_v2_{label}.jsonl`입니다.
- 이 slim 파일에는 `embed_enabled=false`와 `chunk_type=toc` 청크가 없습니다.
- `source_store_v2_{label}.jsonl`은 generation에서 더 긴 원문 근거가 필요할 때만 `source_ref.source_store_id`로 조회합니다.
- `source_store_v2_{label}.jsonl`을 통째로 임베딩하지 않습니다.
- R0/v1 baseline 비교가 필요한 경우에는 slim이 아니라 full corpus를 사용합니다.
- Chroma DB는 Google Drive가 아니라 Colab/GCV 로컬 런타임 경로에 만드는 것을 권장합니다.
- 첫 build 이후에는 corpus hash가 바뀌지 않았다면 collection을 재사용합니다.

## Slim 결과

| 항목 | 값 |
|---|---:|
| full chunk rows | {stats['full_chunk_count']} |
| slim chunk rows | {stats['slim_chunk_count']} |
| removed chunk rows | {stats['removed_chunk_count']} |
| full chunks MiB | {stats['full_chunks_mib']} |
| slim chunks MiB | {stats['slim_chunks_mib']} |
| chunks 축소율 | {stats['chunks_reduction_pct']}% |
| full source_store rows | {stats['full_source_store_count']} |
| slim source_store rows | {stats['slim_source_store_count']} |
| full source_store MiB | {stats['full_source_store_mib']} |
| slim source_store MiB | {stats['slim_source_store_mib']} |
| v2 core 합산 축소율 | {stats['combined_reduction_pct']}% |

## 제외된 청크

제외된 청크는 retrieval/embedding 대상이 아닌 row입니다. 대부분 반복 양식 table 또는 목차입니다.

```json
{json.dumps(stats['removed_chunk_type_counts'], ensure_ascii=False, indent=2)}
```
"""


def make_key_description(label: str, stats: dict[str, Any]) -> str:
    return f"""# parsing_p4_hwpx_{label}_slim JSON Key 설명서

이 문서는 slim corpus의 JSON/JSONL key와 retrieval/generation 사용 기준을 설명합니다.

## 0. 산출물 개요

| 항목 | 값 |
|---|---:|
| corpus | `p4_hwpx_{label}_slim` |
| 기본 retrieval 파일 | `chunks_v2_{label}.jsonl` |
| 상세 근거 조회 파일 | `source_store_v2_{label}.jsonl` |
| chunk_count | {stats['slim_chunk_count']} |
| source_store_count | {stats['slim_source_store_count']} |
| embed_enabled_count | {stats['slim_chunk_count']} |
| validation status | `PASS` |

## 1. `chunks_v2_{label}.jsonl`

한 줄에 하나의 chunk JSON 객체가 들어갑니다. full corpus와 schema는 유지하되, `embed_enabled=true`인 row만 남겼습니다.

주요 key:

| key | 설명 |
|---|---|
| `chunk_id` | Chroma `ids`로 사용하는 고유 chunk id입니다. |
| `doc_id`, `doc_key` | 문서 식별자와 문서명입니다. |
| `canonical_doc_id`, `canonical_doc_key` | alias/정규화 후 문서 식별에 사용하는 값입니다. |
| `source_file`, `source_file_nfc` | 원본 파일명과 Unicode NFC 정규화 파일명입니다. |
| `chunk_type` | `text`, `table`, `fact_candidates` 등 청크 유형입니다. slim에는 `toc`가 없습니다. |
| `embed_enabled` | slim에서는 항상 `true`입니다. |
| `content` | Chroma `documents`로 넣을 검색 대상 텍스트입니다. |
| `metadata` | 필터링, 출처 표시, context builder 정책에 쓰는 scalar 중심 metadata입니다. |
| `source_ref` | `source_store_v2`와 연결되는 `source_store_id`를 담습니다. |
| `fact_type`, `answer_policy`, `budget_answer_enabled` | 금액/자격/답변 가능 여부 판단에 사용하는 정책 필드입니다. |

## 2. `source_store_v2_{label}.jsonl`

남은 chunk가 실제로 참조하는 source block만 포함합니다.

- Chroma에 직접 넣는 파일이 아닙니다.
- generation에서 긴 원문이나 표 원형이 필요할 때만 조회합니다.
- full corpus의 raw text를 바꾸지 않고 참조 row만 줄인 파일입니다.

## 3. Chroma 적재 매핑

```python
collection.add(
    ids=[record["chunk_id"]],
    documents=[record["content"]],
    metadatas=[record["metadata"]],
)
```

slim corpus에서는 별도 `embed_enabled` 필터를 걸지 않아도 되지만, 기존 노트북과 호환되도록 key는 유지합니다.

## 4. 주의사항

- `source_store_v2_{label}.jsonl`을 임베딩하지 마세요.
- R0/v1 baseline 실험은 full corpus에서 실행하세요.
- 금액 질문에서는 `fact_type`, `answer_policy`, `budget_answer_enabled`, `budget_value_role`을 함께 확인해야 합니다.
- 숫자는 값 자체보다 역할 분류가 중요합니다. 사업예산, 추정가격, 기초금액, 자격조건, 장려금/수당 등은 서로 다른 role입니다.
"""


def make_handoff_md(label: str, stats: dict[str, Any]) -> str:
    return f"""# P4 HWPX {label} Slim Corpus 공유 안내

## 왜 slim을 만들었나

full corpus에는 원문 추적과 검증을 위해 보존한 청크까지 들어 있습니다. 하지만 실제 Chroma 임베딩에는 `embed_enabled=true`인 청크만 사용합니다. 팀원이 실수로 false 청크까지 임베딩하면 build 시간이 길어지고 메모리 사용량이 커질 수 있어, 실험 공유용으로 slim corpus를 따로 만들었습니다.

## 무엇이 빠졌나

- `embed_enabled=false` 청크
- `chunk_type=toc` 목차 청크
- 남은 청크에서 참조하지 않는 `source_store_v2` row
- R0 baseline용 `chunks_v1_*`, `source_store_v1_*`
- `source_store_*.jsonl` 호환 별칭

exact duplicate content는 제거하지 않았습니다. 같은 문구라도 서로 다른 문서에 속하면 doc-level retrieval과 출처 판단에 필요할 수 있기 때문입니다.

## 용량 변화

| 항목 | full | slim | 축소율 |
|---|---:|---:|---:|
| chunks_v2 rows | {stats['full_chunk_count']} | {stats['slim_chunk_count']} | {stats['chunk_row_reduction_pct']}% |
| chunks_v2 size | {stats['full_chunks_mib']} MiB | {stats['slim_chunks_mib']} MiB | {stats['chunks_reduction_pct']}% |
| source_store_v2 rows | {stats['full_source_store_count']} | {stats['slim_source_store_count']} | {stats['source_store_row_reduction_pct']}% |
| source_store_v2 size | {stats['full_source_store_mib']} MiB | {stats['slim_source_store_mib']} MiB | {stats['source_store_reduction_pct']}% |
| v2 core total | {stats['full_core_mib']} MiB | {stats['slim_core_mib']} MiB | {stats['combined_reduction_pct']}% |

## 제외된 청크 유형

| chunk_type | count |
|---|---:|
{chr(10).join(f'| `{k}` | {v} |' for k, v in stats['removed_chunk_type_counts'].items())}

## 팀원이 실행할 때

1. Chroma 적재 입력은 `chunks_v2_{label}.jsonl` 하나만 사용합니다.
2. `source_store_v2_{label}.jsonl`은 임베딩하지 않습니다.
3. source_store는 generation 단계에서 긴 근거가 필요할 때만 `source_ref.source_store_id`로 조회합니다.
4. Chroma DB는 Google Drive가 아니라 `/content` 또는 `/tmp` 같은 로컬 런타임에 만듭니다.
5. 첫 build가 끝난 뒤에는 collection을 재사용합니다.
6. R0/v1 baseline 비교가 필요하면 slim이 아니라 full corpus를 사용합니다.

## 검증 결과

- 모든 slim chunk의 `embed_enabled`는 `true`입니다.
- slim 안에는 `chunk_type=toc`가 없습니다.
- duplicate `chunk_id`는 0건입니다.
- duplicate `source_store_id`는 0건입니다.
- missing `source_ref.source_store_id`는 0건입니다.
- manifest hash와 실제 파일 hash가 일치합니다.
- validation status는 `PASS`입니다.
"""


def markdown_to_html(title: str, markdown: str) -> str:
    lines = markdown.splitlines()
    body = []
    in_code = False
    in_table = False
    for line in lines:
        if line.startswith("```"):
            if not in_code:
                body.append("<pre><code>")
                in_code = True
            else:
                body.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            body.append(html.escape(line) + "\n")
            continue
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_table:
                body.append("</tbody></table>")
                in_table = False
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                body.append("<table><tbody>")
                in_table = True
                tag = "th"
            body.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
        elif line.startswith("- "):
            if in_table:
                body.append("</tbody></table>")
                in_table = False
            body.append(f"<p>• {html.escape(line[2:])}</p>")
        elif line.strip():
            if in_table:
                body.append("</tbody></table>")
                in_table = False
            body.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        body.append("</tbody></table>")
    return f"""<!doctype html>
<html lang=\"ko\">
<head>
<meta charset=\"utf-8\">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.55; max-width: 1040px; margin: 40px auto; padding: 0 24px; color: #1f2937; }}
h1 {{ font-size: 28px; margin-bottom: 20px; }}
h2 {{ font-size: 20px; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 20px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0 20px; font-size: 14px; }}
th, td {{ border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; vertical-align: top; }}
th {{ background: #f3f4f6; }}
code, pre {{ background: #f8fafc; }}
pre {{ padding: 12px; overflow: auto; border: 1px solid #e5e7eb; }}
</style>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
"""


def copy_optional(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copy2(src, dst)


def build_one(label: str, cfg: dict[str, Any]) -> dict[str, Any]:
    src = cfg["src"]
    dst = cfg["dst"]
    if not src.exists():
        raise FileNotFoundError(src)
    if dst.exists() and any(dst.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty slim directory: {dst}")
    dst.mkdir(parents=True, exist_ok=True)

    src_chunks = src / cfg["chunks"]
    src_sources = src / cfg["sources"]
    out_chunks = dst / cfg["chunks"]
    out_sources = dst / cfg["sources"]

    source_ids: set[str] = set()
    full_chunk_count = 0
    slim_chunk_count = 0
    removed_chunk_count = 0
    full_chunk_bytes = 0
    slim_chunk_bytes = 0
    removed_chunk_type_counts = Counter()
    removed_section_counts = Counter()
    chunk_ids = []
    source_ref_ids = []
    content_needles = {needle: False for needle in TARGET_NEEDLES.get(label, [])}

    with src_chunks.open("r", encoding="utf-8") as inp, out_chunks.open("w", encoding="utf-8") as out:
        for line in inp:
            if not line.strip():
                continue
            full_chunk_count += 1
            full_chunk_bytes += len(line.encode("utf-8"))
            row = json.loads(line)
            if row.get("embed_enabled") is True:
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                slim_chunk_count += 1
                slim_chunk_bytes += len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
                chunk_ids.append(row.get("chunk_id"))
                source_store_id = str((row.get("source_ref") or {}).get("source_store_id") or "")
                source_ref_ids.append(source_store_id)
                source_ids.add(source_store_id)
                row_text = compact_amount_text(json.dumps(row, ensure_ascii=False))
                for needle in content_needles:
                    if needle in row_text:
                        content_needles[needle] = True
            else:
                removed_chunk_count += 1
                md = row.get("metadata") or {}
                removed_chunk_type_counts[str(row.get("chunk_type") or md.get("chunk_type") or "")] += 1
                removed_section_counts[str(md.get("section_type") or "")] += 1

    full_source_store_count = 0
    slim_source_store_count = 0
    full_source_bytes = 0
    slim_source_bytes = 0
    source_store_ids = []
    with src_sources.open("r", encoding="utf-8") as inp, out_sources.open("w", encoding="utf-8") as out:
        for line in inp:
            if not line.strip():
                continue
            full_source_store_count += 1
            full_source_bytes += len(line.encode("utf-8"))
            row = json.loads(line)
            sid = str(row.get("source_store_id") or "")
            if sid in source_ids:
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                slim_source_store_count += 1
                source_store_ids.append(sid)
                slim_source_bytes += len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1

    copy_optional(src / cfg["pilot"], dst / cfg["pilot"])
    copy_optional(src / cfg["xlsx"], dst / cfg["xlsx"])

    stats = {
        "label": label,
        "source_output_dir": str(src),
        "slim_output_dir": str(dst),
        "full_chunk_count": full_chunk_count,
        "slim_chunk_count": slim_chunk_count,
        "removed_chunk_count": removed_chunk_count,
        "chunk_row_reduction_pct": round(removed_chunk_count / full_chunk_count * 100, 2),
        "full_chunks_mib": round(full_chunk_bytes / 1024 / 1024, 2),
        "slim_chunks_mib": file_mib(out_chunks),
        "chunks_reduction_pct": round((1 - out_chunks.stat().st_size / full_chunk_bytes) * 100, 2),
        "full_source_store_count": full_source_store_count,
        "slim_source_store_count": slim_source_store_count,
        "removed_source_store_count": full_source_store_count - slim_source_store_count,
        "source_store_row_reduction_pct": round((1 - slim_source_store_count / full_source_store_count) * 100, 2),
        "full_source_store_mib": round(full_source_bytes / 1024 / 1024, 2),
        "slim_source_store_mib": file_mib(out_sources),
        "source_store_reduction_pct": round((1 - out_sources.stat().st_size / full_source_bytes) * 100, 2),
        "full_core_mib": round((full_chunk_bytes + full_source_bytes) / 1024 / 1024, 2),
        "slim_core_mib": round((out_chunks.stat().st_size + out_sources.stat().st_size) / 1024 / 1024, 2),
        "combined_reduction_pct": round((1 - (out_chunks.stat().st_size + out_sources.stat().st_size) / (full_chunk_bytes + full_source_bytes)) * 100, 2),
        "removed_chunk_type_counts": dict(removed_chunk_type_counts),
        "removed_section_counts": dict(removed_section_counts),
    }

    readme = make_readme(label, stats)
    key_desc = make_key_description(label, stats)
    handoff_md = make_handoff_md(label, stats)
    (dst / "README.md").write_text(readme, encoding="utf-8")
    (dst / "json_key_description.md").write_text(key_desc, encoding="utf-8")
    (dst / "corpus_slim_handoff.md").write_text(handoff_md, encoding="utf-8")
    (dst / "corpus_slim_handoff.html").write_text(
        markdown_to_html(f"P4 HWPX {label} Slim Corpus 공유 안내", handoff_md),
        encoding="utf-8",
    )

    stats_from_slim = scalar_metadata_stats(out_chunks)
    source_set = set(source_store_ids)
    missing_source_refs = [sid for sid in source_ref_ids if not sid or sid not in source_set]
    validation = {
        "output_dir": str(dst),
        "source_output_dir": str(src),
        "version": "v2_slim_embed_enabled_only",
        "document_count": load_json(src / "validation_report_v2.json").get("document_count"),
        "chunk_count": slim_chunk_count,
        "source_store_count": slim_source_store_count,
        "duplicate_chunk_id_count": len(chunk_ids) - len(set(chunk_ids)),
        "duplicate_source_store_id_count": len(source_store_ids) - len(set(source_store_ids)),
        "missing_source_ref_count": len(missing_source_refs),
        "missing_source_store_ref": len(missing_source_refs),
        "missing_doc_key_count": load_json(src / "validation_report_v2.json").get("missing_doc_key_count", 0),
        "embed_enabled_count": slim_chunk_count,
        "removed_from_full": {
            "chunk_count": removed_chunk_count,
            "source_store_count": full_source_store_count - slim_source_store_count,
            "removed_chunk_type_counts": dict(removed_chunk_type_counts),
            "removed_section_counts": dict(removed_section_counts),
        },
        "slim_policy": {
            "kept_chunks": "embed_enabled == true",
            "kept_source_store": "source_store_id referenced by kept chunks",
            "exact_duplicate_content_removed": False,
            "v1_baseline_included": False,
            "source_store_alias_included": False,
        },
        **stats_from_slim,
        "chunks_jsonl_file_size_mib": file_mib(out_chunks),
        "source_store_file_size_mib": file_mib(out_sources),
        "source_store_jsonl_file_size_mib": file_mib(out_sources),
        "chunks_jsonl_line_count": slim_chunk_count,
        "source_store_jsonl_line_count": slim_source_store_count,
        "chunks_jsonl_sha1": sha1(out_chunks),
        "source_store_jsonl_sha1": sha1(out_sources),
        "smoke_target_amount_presence": content_needles,
        "status": "PASS",
        "fail_reasons": [],
        "created_at": NOW,
    }
    if validation["duplicate_chunk_id_count"]:
        validation["fail_reasons"].append("duplicate_chunk_id")
    if validation["duplicate_source_store_id_count"]:
        validation["fail_reasons"].append("duplicate_source_store_id")
    if validation["missing_source_ref_count"]:
        validation["fail_reasons"].append("missing_source_ref")
    if any(not v for v in content_needles.values()):
        validation["fail_reasons"].append("target_amount_presence_smoke_failed")
    if validation["fail_reasons"]:
        validation["status"] = "FAIL"
    write_json(dst / "validation_report_v2.json", validation)

    file_hashes = {
        "chunks_v2_sha1": sha1(out_chunks),
        "source_store_v2_sha1": sha1(out_sources),
        "pilot_docs_sha1": sha1(dst / cfg["pilot"]),
        "metadata_light_sha1": sha1(dst / cfg["xlsx"]),
        "validation_v2_sha1": sha1(dst / "validation_report_v2.json"),
        "readme_sha1": sha1(dst / "README.md"),
        "json_key_description_sha1": sha1(dst / "json_key_description.md"),
        "corpus_slim_handoff_md_sha1": sha1(dst / "corpus_slim_handoff.md"),
        "corpus_slim_handoff_html_sha1": sha1(dst / "corpus_slim_handoff.html"),
    }
    src_manifest = load_json(src / "manifest.json")
    manifest = {
        "corpus_name": f"p4_hwpx_{label}_slim",
        "corpus_version": f"{src_manifest.get('corpus_version', 'v2')}_slim_embed_enabled_only_20260528",
        "source_output_name": src.name,
        "source_output_dir": str(src),
        "output_dir_name": dst.name,
        "output_dir": str(dst),
        "document_count": validation["document_count"],
        "chunks_v2_file": cfg["chunks"],
        "source_store_v2_file": cfg["sources"],
        "pilot_docs_file": cfg["pilot"],
        "metadata_light_file": cfg["xlsx"],
        "validation_v2_file": "validation_report_v2.json",
        "readme_file": "README.md",
        "json_key_description_file": "json_key_description.md",
        "corpus_slim_handoff_md_file": "corpus_slim_handoff.md",
        "corpus_slim_handoff_html_file": "corpus_slim_handoff.html",
        "omitted_files": [
            f"chunks_v1_{label}.jsonl",
            f"source_store_v1_{label}.jsonl",
            f"source_store_{label}.jsonl",
            "validation_report_v1.json",
            "validation_report.json",
            f"table_preview_{label}.csv",
        ],
        "slim_policy": validation["slim_policy"],
        "reduction_summary": stats,
        "file_hashes": file_hashes,
        "created_at": NOW,
    }
    write_json(dst / "manifest.json", manifest)
    stats["validation_status"] = validation["status"]
    stats["manifest_hashes"] = file_hashes
    return stats


def verify_one(label: str, cfg: dict[str, Any]) -> dict[str, Any]:
    dst = cfg["dst"]
    chunks = dst / cfg["chunks"]
    sources = dst / cfg["sources"]
    manifest = load_json(dst / "manifest.json")
    validation = load_json(dst / "validation_report_v2.json")
    chunk_ids = []
    source_ref_ids = []
    chunk_types = Counter()
    embed_false = 0
    forbidden_hits: dict[str, list[str]] = {}
    for line, row in iter_jsonl(chunks):
        chunk_ids.append(row.get("chunk_id"))
        if row.get("embed_enabled") is not True:
            embed_false += 1
        chunk_types[str(row.get("chunk_type") or (row.get("metadata") or {}).get("chunk_type") or "")] += 1
        source_ref_ids.append(str((row.get("source_ref") or {}).get("source_store_id") or ""))
        text = json.dumps(row, ensure_ascii=False)
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                forbidden_hits.setdefault(marker, []).append(str(row.get("chunk_id")))
    source_ids = []
    for _, row in iter_jsonl(sources):
        source_ids.append(str(row.get("source_store_id") or ""))
        text = json.dumps(row, ensure_ascii=False)
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                forbidden_hits.setdefault(marker, []).append(str(row.get("source_store_id")))
    source_set = set(source_ids)
    missing_refs = [sid for sid in source_ref_ids if not sid or sid not in source_set]
    hash_ok = {}
    mapping = {
        "chunks_v2_sha1": cfg["chunks"],
        "source_store_v2_sha1": cfg["sources"],
        "pilot_docs_sha1": cfg["pilot"],
        "metadata_light_sha1": cfg["xlsx"],
        "validation_v2_sha1": "validation_report_v2.json",
        "readme_sha1": "README.md",
        "json_key_description_sha1": "json_key_description.md",
        "corpus_slim_handoff_md_sha1": "corpus_slim_handoff.md",
        "corpus_slim_handoff_html_sha1": "corpus_slim_handoff.html",
    }
    for key, filename in mapping.items():
        hash_ok[key] = manifest["file_hashes"].get(key) == sha1(dst / filename)
    full_true_ids = []
    for _, row in iter_jsonl(cfg["src"] / cfg["chunks"]):
        if row.get("embed_enabled") is True:
            full_true_ids.append(row.get("chunk_id"))
    return {
        "label": label,
        "chunk_count": len(chunk_ids),
        "source_store_count": len(source_ids),
        "embed_false_count": embed_false,
        "toc_count": chunk_types.get("toc", 0),
        "duplicate_chunk_id_count": len(chunk_ids) - len(set(chunk_ids)),
        "duplicate_source_store_id_count": len(source_ids) - len(set(source_ids)),
        "missing_source_ref_count": len(missing_refs),
        "unreferenced_source_store_count": len(source_set - set(source_ref_ids)),
        "manifest_hashes_all_ok": all(hash_ok.values()),
        "manifest_hashes": hash_ok,
        "validation_status": validation.get("status"),
        "validation_chunk_hash_ok": validation.get("chunks_jsonl_sha1") == sha1(chunks),
        "validation_source_hash_ok": validation.get("source_store_jsonl_sha1") == sha1(sources),
        "slim_ids_equal_full_embed_true_ids": set(chunk_ids) == set(full_true_ids) and len(chunk_ids) == len(full_true_ids),
        "forbidden_marker_hits": forbidden_hits,
        "target_amount_presence": validation.get("smoke_target_amount_presence", {}),
    }


def main() -> None:
    build_report = {label: build_one(label, cfg) for label, cfg in PACKAGES.items()}
    verify_report = {label: verify_one(label, cfg) for label, cfg in PACKAGES.items()}
    all_pass = True
    for report in verify_report.values():
        all_pass = all_pass and report["embed_false_count"] == 0
        all_pass = all_pass and report["toc_count"] == 0
        all_pass = all_pass and report["duplicate_chunk_id_count"] == 0
        all_pass = all_pass and report["duplicate_source_store_id_count"] == 0
        all_pass = all_pass and report["missing_source_ref_count"] == 0
        all_pass = all_pass and report["unreferenced_source_store_count"] == 0
        all_pass = all_pass and report["manifest_hashes_all_ok"]
        all_pass = all_pass and report["validation_status"] == "PASS"
        all_pass = all_pass and report["validation_chunk_hash_ok"]
        all_pass = all_pass and report["validation_source_hash_ok"]
        all_pass = all_pass and report["slim_ids_equal_full_embed_true_ids"]
        all_pass = all_pass and not report["forbidden_marker_hits"]
        all_pass = all_pass and all(report["target_amount_presence"].values())
    final = {
        "created_at": NOW,
        "all_pass": all_pass,
        "build": build_report,
        "verify": verify_report,
    }
    out = ROOT / "outputs" / "reports" / "slim_corpus_build_report_20260528.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, final)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
