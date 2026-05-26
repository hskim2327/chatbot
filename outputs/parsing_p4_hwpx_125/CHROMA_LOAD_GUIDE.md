# P4 HWPX 125 Chroma 적재 가이드

P4 HWPX 125 corpus를 Colab 또는 GCP에서 Chroma에 적재하고 retrieval quickcheck를 돌릴 때 필요한 기준입니다.

## 1. 어떤 파일을 써야 하나?

기본 retrieval 실험은 아래 파일을 사용합니다.

```text
outputs/parsing_p4_hwpx_125/chunks_v2_125.jsonl
```

비교 실험이 필요하면 v1 baseline도 사용할 수 있습니다.

```text
outputs/parsing_p4_hwpx_125/chunks_v1_125.jsonl
```

`metadata_light_125.xlsx`는 사람이 검토하기 위한 참고 파일입니다. 임베딩 대상이 아닙니다.
`source_store_125.jsonl`은 긴 원문/표 구조 근거 조회용입니다. Chroma metadata에 그대로 넣지 않습니다.

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
notebooks/rag/embedding_retrieval_eval_p4_hwpx_125_quickcheck.ipynb
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
Chroma path: /content/chroma_p4_hwpx_125
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

path = Path("outputs/parsing_p4_hwpx_125/chunks_v2_125.jsonl")
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
