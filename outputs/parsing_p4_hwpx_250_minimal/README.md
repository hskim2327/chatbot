# P4 HWPX 250 Minimal Corpus

P4 690 corpus에서 eval 정답 문서를 우선 포함하도록 문서 단위로 250개를 추린 가벼운 테스트용 corpus입니다.
Chroma 적재와 빠른 리트리벌 실험을 먼저 확인하고 싶은 경우 사용하시면 됩니다.

기본 경로 예시는 아래와 같습니다.

```text
outputs/parsing_p4_hwpx_250_minimal/
├─ chunks_v2_250.jsonl
├─ metadata_light_250.xlsx
├─ validation_report.json
├─ manifest.json
├─ CHROMA_LOAD_GUIDE.md
└─ chroma_load_example.py
```

## 핵심 파일

| 파일 | 용도 | 공유/업로드 기준 |
|---|---|---|
| `chunks_v2_250.jsonl` | Chroma 적재용 구조화 corpus입니다. `text/table/fact_candidates`가 포함됩니다. | 필수 |
| `metadata_light_250.xlsx` | 문서별 요약/검증용 참고 파일입니다. 공고번호, 입찰마감일시, 사업명, 기관명 등을 확인할 수 있습니다. | 필수 |
| `validation_report.json` | 250개 corpus 검증 결과입니다. | 참고 |
| `manifest.json` | corpus 이름, 버전, 주요 파일명을 기록한 작은 설정/목록 파일입니다. | 참고 |
| `CHROMA_LOAD_GUIDE.md` | Chroma 적재/Colab/GCP 주의사항입니다. | 필수 |
| `chroma_load_example.py` | Chroma 적재 예시 코드입니다. | 선택 |

## 선택 기준

단순히 P4 690에서 앞의 250개를 자른 파일이 아닙니다.

```text
1. eval 에서 확인되는 eval ground_truth_docs 문서를 먼저 포함
2. 남은 개수는 P4 690 metadata의 rank_index 순서대로 filler 문서 추가
3. 총 250개 문서로 고정
```

따라서 빠른 테스트에서도 eval 정답 문서가 corpus 밖에 있어서 맞힐 수 없는 상황을 줄이도록 구성했습니다.

## Validation 요약

| 항목 | 값 |
|---|---:|
| 문서 수 | 250 |
| chunk 수 | 41,574 |
| embed 대상 | 41,468 |
| duplicate chunk_id | 0 |
| missing content | 0 |
| missing source ref | 0 |
| JSONL 크기 | 88.15 MiB |
| metadata Excel 크기 | 0.86 MiB |
| validation | PASS |



## Chroma 적재 기준

```text
ids       = chunk_id
documents = content
metadatas = metadata
```

기본 적재 대상은 `chunks_v2_250.jsonl`에서 아래 조건을 만족하는 record입니다.

```text
embed_enabled == true
chunk_type != "toc"
content가 비어 있지 않음
```

## 엑셀 파일에 들어있는 주요 정보

`metadata_light_250.xlsx`

- 문서명: `source_file`
- eval 정답 문서 여부: `eval_gt_doc_any_batch`, `official_eval_gt_doc_batch01_25`
- 파싱 방식: `source_format`, `parser_status`
- 사업명/기관명: `project_name`, `issuer`
- 공고번호/공고차수: `공고번호`, `공고차수`
- 입찰마감일시: `입찰마감일시`
- 사업금액/사업기간: `final_budget`, `final_project_duration`
- 제출서류/입찰자격: `final_submission_documents`, `final_bid_eligibility_terms`
- G2B 매칭 상태: `G2B_매칭상태`, `G2B_매칭점수`
- 본문 미리보기: `text_preview_5000` (엑셀 가독성이 안 좋아져서 숨김처리 해놨습니다!)


## 주의

- 이 250개 corpus는 빠른 테스트용입니다. 최종 성능 평가는 690개 전체 corpus로 다시 확인해야 합니다.
- 250개는 distractor 문서 수가 690개보다 적기 때문에 리트리벌 점수가 실제 최종 환경보다 높게 나올 수 있습니다.
- Chroma DB는 Google Drive에 만들지 않는 것을 권장합니다. Colab에서는 `/content/...`, GCP에서는 VM 로컬 SSD 또는 `/tmp/...`를 우선 사용해 주세요.
- `.npy` embedding cache는 기본 산출물이 아닙니다. 같은 corpus, 같은 chunk 순서, 같은 embedding model로 Chroma를 여러 번 재생성해야 할 때만 임시로 1개를 재사용하세요. 실험이 끝났거나 경로/모델/청크 순서가 바뀌면 삭제하는 것이 안전합니다.
- `source_store`, Chroma DB, embedding cache, 원본 HWP/HWPX/PDF는 이 최소 공유 폴더에 포함하지 않았습니다.

자세한 적재 방식은 `CHROMA_LOAD_GUIDE.md`와 `chroma_load_example.py`를 참고 부탁드립니다.
