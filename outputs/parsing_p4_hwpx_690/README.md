# P4 HWPX 690 Retrieval-Ready Corpus

P4는 690개 RFP 문서를 HWPX/PDF/HWP fallback으로 파싱해 만든 retrieval-ready corpus입니다.
Chroma에 바로 적재할 수 있도록 `chunk_id / content / metadata` 중심으로 구성했습니다.

## 핵심 파일

| 파일 | 용도 | 공유/업로드 기준 |
|---|---|---|
| `chunks_v2_690.jsonl` | 기본 Chroma 적재용 구조화 corpus입니다. `text/table/fact_candidates`가 포함됩니다. | 
| `chunks_v1_690.jsonl` | clean text baseline입니다. 베이스라인 비교 실험용입니다. | 선택사항이므로 필요하신 분만 사용 |
| `metadata_light_690.xlsx` | 문서별 요약/검증용 참고 파일입니다. | 
| `validation_report.json` | v2 검증 결과로  참고 파일입니다. |
| `validation_report_v1.json` | v1 검증 결과로  참고 파일입니다. |
| `CHROMA_LOAD_GUIDE.md` | Chroma 적재/Colab/GCP 주의사항입니다. | 
| `chroma_load_example.py` | Chroma 적재 예시 코드입니다. | 
| `json_key_description_p4_hwpx_690.md` | `chunks_v2_690.jsonl`의 주요 JSON key와 Chroma 매핑 방식을 설명한 문서입니다. | 처음 사용하는 분은 먼저 확인 권장 |


## Validation 요약

| 항목 | v1 clean text | v2 structured |
|---|---:|---:|
| 문서 수 | 690 | 690 |
| 파싱 성공 | 690 | 690 |
| 실패 | 0 | 0 |
| chunk 수 | 75,912 | 124,740 |
| embed 대상 | 75,638 | 124,472 |
| duplicate chunk_id | 0 | 0 |
| missing source ref | 0 | 0 |
| JSONL 크기 | 189.18 MiB | 251.44 MiB |
| validation | PASS | PASS |

## Chroma 적재 기준

```text
ids       = chunk_id
documents = content
metadatas = metadata
```

기본 적재 대상은 `chunks_v2_690.jsonl`에서 아래 조건을 만족하는 record입니다.

```text
embed_enabled == true
chunk_type != "toc"
content가 비어 있지 않음
```


## 엑셀 파일에 들어있는 주요 정보는:

`metadata_light_690.xlsx`

문서명: source_file
파싱 방식: source_format, parser_status
사업명/기관명: project_name, issuer
사업금액/사업기간: final_budget, final_project_duration
공고번호/공고차수: notice_id_final, notice_round_final
입찰마감일: bid_deadline_final
제출서류/입찰자격: final_submission_documents, final_bid_eligibility_terms
G2B 매칭 상태: g2b_match_status, g2b_match_score
본문 미리보기: text_preview_5000 (미리보기로 인해 가독성이 떨어져서 컬럼 1개(BN)를 숨김 처리해놨습니다.)


## 주의

- Chroma DB는 Google Drive에 만들지 않는 것을 권장합니다. Colab에서는 `/content/...`, GCP에서는 VM 로컬 SSD 또는 `/tmp/...`를 우선 사용해 주세용!
- `.npy` embedding cache는 기본 산출물이 아닙니다. 같은 corpus, 같은 chunk 순서, 같은 embedding model로 Chroma를 여러 번 재생성해야 할 때만 임시로 1개를 재사용하세요. Chroma 적재가 끝났거나 경로/모델/청크 순서가 바뀌면 삭제하는 것이 안전합니다. 690개 전체에서는 캐시/Chroma/원본 JSON이 겹치면 디스크가 빠르게 찰 수 있습니다.
- `source_store_690.jsonl`은 Chroma에 넣는 파일이 아닙니다. 필요할 때 원문 근거를 더 길게 확인하기 위한 선택 파일입니다.

JSON key 구조는 `json_key_description_p4_hwpx_690.md`를 먼저 확인하시면 됩니다.
자세한 Chroma 적재 방식은 `CHROMA_LOAD_GUIDE.md`와 `chroma_load_example.py`를 참고 부탁드립니다!
