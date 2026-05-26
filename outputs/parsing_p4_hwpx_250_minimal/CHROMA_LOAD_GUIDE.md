# P4 690 Chroma 적재 가이드

P4 690 corpus를 Colab 또는 GCP에서 Chroma에 적재할 때 주의해야 할 점을 정리했습니다.

## 1. 어떤 파일을 써야 하나?

기본 실험은 아래 파일 하나만 사용하면 됩니다.

```text
data/chunks_v2_690.jsonl
```

비교 실험이 필요하면 v1 baseline도 사용합니다.

```text
data/chunks_v1_690.jsonl
```

`metadata_light_690.xlsx`는 사람이 검토하기 위한 참고 파일입니다. 임베딩 대상이 아닙니다.


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

(metadata에 긴 원문, table 전체 JSON, OCR 전문, rows/list/dict를 그대로 넣지 않습니다!)

## 3. 반드시 필터링할 것

적재 전 아래 조건을 적용하세요.

```python
record.get("embed_enabled") is True
record.get("chunk_type") != "toc"
record.get("content", "").strip() != ""
```

`toc`는 구조 파악용으로 보존하지만 기본 임베딩에서는 제외합니다.

## 4. Colab 환경에서 주의할 점

Colab에서는 Google Drive에 Chroma DB를 직접 만들지 않는 것이 좋습니다.
Drive는 동기화 I/O가 느리고 파일이 많이 생기면 멈춘 것처럼 보일 수 있습니다.

권장:

```text
Chroma path: /content/chroma_p4_690
결과 CSV/predictions: /content/drive/MyDrive/Codeit_Project/outputs/...
```

즉, Chroma DB는 런타임 로컬에 만들고, 최종 결과 CSV만 Drive에 저장하세요.
런타임을 끊으면 Chroma DB는 사라져도 됩니다. 다시 만들 수 있는 산출물이기 때문입니다.

## 5. GCP VM에서 주의할 점

GCP에서는 디스크 용량을 먼저 확인하세요.

```bash
df -h
```

Chroma 경로는 프로젝트 폴더 내부보다 VM 로컬 작업 디스크를 권장합니다.

예:

```text
/tmp/chroma_p4_690
/mnt/disks/work/chroma_p4_690
```

주의:

- Chroma DB와 embedding cache를 Git 폴더 안에 만들면 안됩니당~
- `git add .` 금지
- `chroma/`, `.cache/`, `*.npy`, `*.parquet`, `*.sqlite3` 등이 올라가지 않도록 `.gitignore`를 확인하세요.

## 6. 디스크 폭발을 막는 원칙

문제가 생기는 조합은 보통 아래입니다.

```text
원본 JSONL
+ source_store
+ Chroma DB
+ embedding .npy cache
+ predictions/logs
+ Google Drive sync
```

아래 사항을 조심해 주시면 좋을 것 같습니다!

1. Chroma DB는 로컬 임시 경로에 생성합니다.
2. `.npy` embedding cache는 기본적으로 만들지 않습니다. 단, 같은 corpus, 같은 chunk 순서, 같은 embedding model로 반복 적재해야 하는 경우에는 임시 cache 1개만 재사용할 수 있습니다. 이 경우 cache key와 chunk_id 순서가 일치하는지 확인하고, 실험이 끝나면 삭제하시면 됩니다!
3. 결과 CSV와 predictions만 저장합니다.


## 7. 적재 전 sanity check

확인할 것:

```text
총 record 수
embed_enabled record 수
chunk_id 중복 수
chunk_type 분포
metadata가 dict인지
content 평균/최대 길이
```

기준:

```text
duplicate chunk_id = 0
empty content = 0
toc는 기본 적재 제외
```

## 8. 예시 코드

필요하신 분은 `chroma_load_example.py`를 참고 부탁드립니다!

실행 예:

```bash
python chroma_load_example.py \
  --chunks data/chunks_v2_690.jsonl \
  --chroma-path /content/chroma_p4_690 \
  --collection rfp_p4_690_v2_koe5
```

Colab에서는 노트북 셀에서 아래처럼 실행할 수 있습니다.

```python
!python /content/drive/MyDrive/Codeit_Project/data/chroma_load_example.py \
  --chunks /content/drive/MyDrive/Codeit_Project/data/chunks_v2_690.jsonl \
  --chroma-path /content/chroma_p4_690 \
  --collection rfp_p4_690_v2_koe5
```
