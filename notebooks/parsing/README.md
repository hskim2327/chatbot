# Parsing Notebooks

RFP 원본(HWP/PDF)을 검색 가능한 JSONL corpus로 바꾸는 단계입니다.

## Files

| 파일 | 용도 |
|---|---|
| `hwp_text_extraction_test.ipynb` | HWP 원문 추출, raw/clean 비교, artifact 후보 검증 |
| `rfp_parsing_v1_v2_pipeline.ipynb` | phase1 기준 v1/v2 파싱 실험 노트북 |
| `rfp_parsing_p2_250_pipeline.ipynb` | phase2 개선 반영 후 250개 pilot corpus 생성 |
| `rfp_parsing_p4_hwpx_125_pipeline.ipynb` | eval 정답 문서 61개를 포함한 P4 HWPX 125개 precision corpus 생성 |
| `../rag/embedding_retrieval_eval_p4_hwpx_125_quickcheck.ipynb` | P4 HWPX 125 corpus를 Chroma에 적재하고 `smoke`/`quick`/`full` 모드로 retrieval 평가 |
| `quick_check_rag_chunks_p2_250.ipynb` | 생성된 chunk 품질, key 결측, 중복, 예산/기간/제출서류 sanity check |
| `json_key_description.md` | P2 JSONL key와 block/chunk 구조 설명 |

## Phase Summary

phase1과 phase2는 하나의 parsing 흐름으로 관리합니다.

| 단계 | 핵심 목적 | 산출물 성격 |
|---|---|---|
| phase1 | HWP/PDF 추출 가능성 확인, v1 clean text와 v2 구조화 corpus 분리 | 기본 구조 검증 |
| phase2 | `chunk_id` 중복 제거, `toc` 분리, artifact cleaner 보강, 사업금액/기간/제출서류/입찰참가자격 추출 로직 개선 | retrieval 실험용 권장 corpus |

P2에서는 목차를 삭제하지 않고 `chunk_type='toc'`, `embed_enabled=False`로 보존합니다. 구조 파악에는 쓰되 기본 Chroma 임베딩에서는 제외합니다.

## Output Policy

아래 산출물은 용량이 커서 GitHub에 포함하지 않습니다.

```text
outputs/parsing_p2_250/
├─ chunks_v1.jsonl
├─ chunks_v2.jsonl
├─ parsed_blocks_v1.jsonl
├─ parsed_blocks_v2.jsonl
├─ rfp_parsing_metadata_250_p2_chunkfix_toc_clean.xlsx
└─ doc_parse_summary.csv
```

필요하면 공유 Drive로 전달하고, 사용자는 같은 경로 구조로 내려받아 노트북을 실행합니다.

## Recommended Corpus

기본 retrieval 실험에는 `outputs/parsing_p2_250/chunks_v2.jsonl`을 사용합니다.

- `v1`: clean text baseline
- `v2_p2`: text/table/fact 후보를 포함한 권장 corpus
- chunk 기준: `1000 / 150`
- 기본 임베딩 대상: `embed_enabled=True` and `chunk_type!='toc'`

## Quality Notes

- HWP 내부 artifact는 raw 추출 결과와 clean 결과를 비교하며 제거했습니다.
- 정상 한자(`現`, `無`, `有`, `乙`, `新` 등)는 제거 대상에서 제외합니다.
- P2 sanity check 기준으로 `chunk_id` 중복은 0건입니다.
- 공고번호와 입찰일자는 원문에 없는 문서가 많아, 없는 값을 억지로 채우지 않습니다.
- `계약 후 10일 이내 사업수행계획서 제출` 같은 표현은 사업기간이 아니라 기타 기한으로 분리합니다.

## Large Input Comment

원본 HWP/PDF와 parsing output은 GitHub에 없습니다. 노트북을 다른 환경에서 실행할 때는 아래 중 하나를 먼저 준비합니다.

```text
data/original_data_list/files_advanced/
공유드라이브 : 코드잇_중급프로젝트_3팀/파싱_청킹_산출물/250_260518
```

Colab/GCP에서는 공유 Drive 또는 VM 디스크에 동일한 구조로 배치한 뒤 경로 설정 셀을 수정합니다.
