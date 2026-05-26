# parsing_p2_250 JSON Key 설명서

이 문서는 `outputs/parsing_p2_250` 산출물의 JSON/JSONL key를 정리한 문서입니다.

- corpus_name: `p2_250`
- corpus_version: `v2_p2`
- parsing label: `p2_chunkfix_toc_clean`
- 기본 retrieval 파일: `chunks_v2.jsonl`
- baseline 비교 파일: `chunks_v1.jsonl`

`jsonl`은 한 줄에 JSON 객체 하나가 들어가는 형식입니다. 파일 전체가 하나의 JSON 배열이 아니라, 각 줄이 독립적인 record입니다.

## P2에서 달라진 점

| 항목 | 변경 내용 |
|---|---|
| `chunk_id` | v1/v2, chunk type, block 번호, part 번호를 포함하도록 변경했습니다. chunk_id 중복은 0건입니다. |
| `toc` | 목차를 삭제하지 않고 `chunk_type='toc'`로 별도 보존합니다. |
| `embed_enabled` | 기본 임베딩 대상 여부를 명시합니다. (참고로 목차인 `toc`는 기본적으로 `False`입니다.) |
| artifact cleaner | HWP 추출 과정에서 섞이던 artifact 문자를 추가 제거했습니다. 정상 한자는 보존합니다. |
| `final_*` key | 사업금액, 사업기간, 제출서류, 입찰참가자격, 날짜 관련 최종 추출값과 근거를 강화했습니다. |
| v2 | text/table/fact 후보를 함께 보존하는 기본 검색 corpus입니다. |

## 대상 파일

| 파일 | 단위 | 설명 |
|---|---:|---|
| `chunks_v2.jsonl` | chunk | 기본 retrieval corpus입니다. text/table/fact 후보를 포함합니다. |
| `chunks_v1.jsonl` | chunk | clean text baseline입니다. R0 같은 비교 실험에 사용합니다. |
| `parsed_blocks_v2.jsonl` | block | chunk 이전의 block 단위 구조화 결과입니다. table/fact 후보를 포함합니다. |
| `parsed_blocks_v1.jsonl` | block | v1 clean text 기준 block 결과입니다. |
| `doc_parse_summary.csv` | document | 문서별 파싱/추출 요약 CSV입니다. |
| `parsing_summary.json` | summary | 전체 파싱 결과 요약 JSON입니다. |

## 1. 공통 문서 메타데이터 key

아래 key는 `chunks_*`, `parsed_blocks_*`에 공통으로 들어갑니다.

| key | 설명 |
|---|---|
| `parser_version` | 파서 버전입니다. 예: `v1`, `v2` |
| `pilot_doc_id` | pilot corpus 내부 문서 ID입니다. 예: `P001` |
| `doc_id` | 파일명 기반 내부 문서 ID입니다. |
| `norm_name` | 정규화된 문서명입니다. |
| `source_file` | 원본 파일명입니다. |
| `file_type` | 원본 파일 형식입니다. 예: `hwp`, `pdf` |
| `project_name` | 사업명 또는 공고명입니다. |
| `issuer` | 발주기관명입니다. |
| `notice_round` | 공고 차수 자리입니다. 현재 대부분 빈 값입니다. |

## 2. 공고번호 key

| key | 설명 |
|---|---|
| `notice_id` | 최종 공고번호와 같은 값으로 유지되는 호환용 key입니다. 없으면 빈 값입니다. |
| `external_notice_id` | 외부 메타데이터 공고번호 자리입니다. 현재 P2 corpus에서는 DB 생성 기준으로 사용하지 않습니다. |
| `final_notice_id` | 원문에서 추출한 최종 공고번호입니다. |
| `notice_id_status` | 공고번호 추출 상태입니다. 예: `extracted`, `missing`, `rejected_blank_form` |
| `notice_id_evidence` | 최종 공고번호 판단의 근거가 된 원문 라인입니다. |

주의: 공고번호는 원문에 없는 문서가 많고 eval 중요도가 낮을 수 있습니다. 검색 필터의 핵심 key로 쓰기보다는 보조 메타데이터로 보는 것이 안전합니다.

## 3. 사업금액 key

| key | 설명 |
|---|---|
| `metadata_budget` | 외부 메타데이터 사업금액 자리입니다. |
| `final_budget` | 원문에서 추출한 최종 사업금액 표현입니다. 예: `242,900,000원` |
| `final_budget_krw` | 원화 기준 숫자형 금액입니다. 예: `242900000` |
| `final_budget_status` | 사업금액 추출 상태입니다. 예: `extracted`, `candidate_only`, `missing` |
| `final_budget_evidence` | 최종 사업금액 판단의 근거 문장입니다. |
| `amounts` | 해당 block/chunk 내부에서 발견된 금액 후보 목록입니다. |

주의: 금액 후보는 표 번호, 배점, 수량 같은 숫자와 혼동될 수 있습니다. 최종값은 `final_budget`, 근거 확인은 `final_budget_evidence`를 우선 봅니다.

## 4. 날짜 key

| key | 설명 |
|---|---|
| `published_at` | 외부 메타데이터 또는 초기 날짜 자리입니다. 현재 대부분 빈 값입니다. |
| `bid_start` | 입찰 시작일 초기 자리입니다. 현재 대부분 빈 값입니다. |
| `bid_deadline` | 입찰 마감일 초기 자리입니다. 현재 대부분 빈 값입니다. |
| `final_published_at` | 원문에서 추출한 최종 공고/공개 일자입니다. |
| `final_bid_start` | 원문에서 추출한 최종 입찰 시작일입니다. |
| `final_bid_deadline` | 원문에서 추출한 최종 입찰 마감일입니다. |
| `published_at_status` | 공개일 추출 상태입니다. |
| `bid_start_status` | 입찰 시작일 추출 상태입니다. |
| `bid_deadline_status` | 입찰 마감일 추출 상태입니다. |
| `published_at_evidence` | 공개일 근거 문장입니다. |
| `bid_start_evidence` | 입찰 시작일 근거 문장입니다. |
| `bid_deadline_evidence` | 입찰 마감일 근거 문장입니다. |
| `dates` | 해당 block/chunk 내부에서 발견된 날짜 후보 목록입니다. |

주의: 모든 RFP에 입찰 기간이 명시되는 것은 아닙니다. `계약일로부터 N개월`, `착수일로부터 N일`처럼 상대 기간만 있는 문서도 있습니다.

## 5. 기간 key

| key | 설명 |
|---|---|
| `final_project_duration` | 최종 사업기간입니다. 예: `계약체결일로부터 5개월` |
| `final_project_duration_evidence` | 사업기간 추출 근거 문장입니다. |
| `final_maintenance_period` | 무상유지보수기간입니다. |
| `final_maintenance_period_evidence` | 무상유지보수기간 근거 문장입니다. |
| `final_warranty_period` | 하자담보책임기간입니다. |
| `final_warranty_period_evidence` | 하자담보책임기간 근거 문장입니다. |
| `final_deadline_terms` | 제출, 승인, 착수 등 기타 기한/기간 표현입니다. |
| `final_deadline_terms_evidence` | 기타 기한/기간 추출 근거 문장입니다. |

주의: `계약체결 후 10일 이내` 같은 표현은 사업기간이 아니라 착수계/계획서 제출 기한일 수 있습니다. P2에서는 이런 표현을 `final_deadline_terms`로 분리하는 방향으로 보정했습니다.

## 6. 입찰참가자격 key

| key | 설명 |
|---|---|
| `final_bid_eligibility_terms` | 최종 입찰참가자격 문장 또는 요약 문자열입니다. |
| `final_bid_eligibility_evidence` | 입찰참가자격 판단의 근거 문장입니다. |

입찰참가자격은 RFP 검색에서 중요도가 높은 영역입니다. 질문이 자격요건, 참여조건, 공동수급, 업종코드 등을 묻는 경우 이 key와 관련 chunk를 우선 확인합니다.

## 7. 제출서류 key

| key | 설명 |
|---|---|
| `submission_doc_terms` | 해당 chunk에서 감지된 제출서류 관련 용어 목록입니다. |
| `final_submission_documents` | `fact_candidates` block의 구조화 데이터 안에 있는 최종 제출서류 후보 목록입니다. |
| `final_submission_documents_text` | 최종 제출서류 후보를 텍스트로 합친 값입니다. |
| `final_submission_document_names` | 제출서류명만 정리한 목록입니다. |
| `final_submission_document_groups_text` | 제출서류 그룹 정보를 텍스트로 정리한 값입니다. |

주의: `제안서`, `발표자료`, `가격제안서`, `입찰서`처럼 실제 제출물이 반복될 수 있습니다. 같은 서류가 여러 문맥에서 반복되면 후처리에서 중복 제거가 필요합니다.

## 8. block 전용 key

`parsed_blocks_v1.jsonl`, `parsed_blocks_v2.jsonl`에 들어가는 key입니다.

| key | 설명 |
|---|---|
| `block_id` | block 고유 ID입니다. 예: `P001_v2_table_0001` |
| `block_type` | block 종류입니다. 예: `toc`, `text`, `table`, `fact_candidates` |
| `section_path` | 문서 내 섹션 경로입니다. list 형태입니다. |
| `section_type` | RFP 도메인 기준 섹션 분류입니다. |
| `text` | block 본문입니다. |
| `structured_data` | table/fact 후보 등 block별 구조화 데이터입니다. |
| `exact_terms` | 정확 매칭에 보존할 핵심 용어 목록입니다. |
| `char_len` | block 텍스트 길이입니다. |

### block_type 값

| 값 | 설명 |
|---|---|
| `toc` | 목차 block입니다. 구조 파악용으로 보존합니다. |
| `text` | 일반 본문 block입니다. |
| `table` | 표 또는 표처럼 보이는 박스형 텍스트 block입니다. |
| `fact_candidates` | 문서 전체에서 뽑은 예산/날짜/기간/자격/제출서류 후보 묶음입니다. |

## 9. chunk 전용 key

`chunks_v1.jsonl`, `chunks_v2.jsonl`에 들어가는 key입니다.

| key | 설명 |
|---|---|
| `chunk_id` | chunk 고유 ID입니다. 예: `P001_v2_text_0001_part_001` |
| `parent_block_id` | 이 chunk가 만들어진 원본 block ID입니다. |
| `chunk_type` | chunk 종류입니다. 예: `toc`, `text`, `table`, `fact_candidates` |
| `embed_enabled` | 기본 임베딩 대상 여부입니다. `toc`는 `False`, 나머지는 대부분 `True`입니다. |
| `section_path` | chunk가 속한 섹션 경로입니다. list 형태입니다. |
| `section_type` | RFP 도메인 기준 섹션 분류입니다. |
| `content` | 실제 임베딩/검색에 사용할 chunk 본문입니다. |
| `exact_terms` | 정확 매칭에 보존할 핵심 용어 목록입니다. |
| `chunk_max_chars` | chunk 최대 글자 수 설정입니다. 현재 1000입니다. |
| `chunk_overlap` | chunk 간 겹침 글자 수 설정입니다. 현재 150입니다. |
| `char_len` | chunk 본문 길이입니다. |
| `part_index` | 하나의 block이 여러 chunk로 쪼개졌을 때 몇 번째 조각인지 나타냅니다. |

### chunk_id 규칙

P2에서는 chunk ID가 아래처럼 생성됩니다.

```text
P001_v1_text_0001_part_001
P001_v2_text_0001_part_001
P001_v2_table_0001_part_001
P001_v2_fact_candidates_0001_part_001
P001_v2_toc_0001_part_001
```

즉, `pilot_doc_id + parser_version + chunk_type + block_index + part_index`를 포함합니다. 이 규칙으로 v1/v2, text/table/fact/toc 간 ID 충돌을 방지합니다.

## 10. structured_data 내부 key

`structured_data`는 `parsed_blocks_v2.jsonl`에서 주로 사용합니다.

### table block

| key | 설명 |
|---|---|
| `rows` | 표/박스형 텍스트를 행 단위로 보존한 값입니다. |
| `raw_lines` | 표 후보로 판단된 원본 줄 목록입니다. |

현재 단계에서는 완전한 행/열 복원보다 RFP 검색에 필요한 표 내부 텍스트 보존을 우선합니다.

### toc block

| key | 설명 |
|---|---|
| `toc_line_count` | 목차로 판단된 줄 수입니다. |

### fact_candidates block

| key | 설명 |
|---|---|
| `notice_id_candidates` | 공고번호 후보 목록입니다. |
| `notice_id_rejected_blank_count` | 공란/서식용 공고번호로 제거된 후보 수입니다. |
| `budget_candidates` | 사업금액 후보 목록입니다. |
| `date_candidates` | 날짜 후보 목록입니다. |
| `period_candidates` | 사업기간/유지보수/하자담보/기한 후보 목록입니다. |
| `eligibility_candidates` | 입찰참가자격 후보 목록입니다. |
| `submission_document_candidates` | 제출서류 후보 목록입니다. |
| `final_*` | 각 항목의 최종 선택값과 근거입니다. |

`fact_candidates`는 검색 품질 점검과 UI 버튼 후보 생성에 유용합니다. 다만 후보 목록은 넓게 잡힌 값이므로 최종 서비스 표시에는 `final_*` 값을 우선 사용합니다.

## 11. doc_parse_summary.csv 주요 컬럼

| 컬럼 | 설명 |
|---|---|
| `pilot_doc_id`, `doc_id`, `source_file` | 문서 식별 정보입니다. |
| `is_eval_ground_truth` | eval 정답 문서에 포함되는지 여부입니다. |
| `parser_status` | 파싱 성공 여부입니다. |
| `parser` | 사용된 추출기입니다. 예: `olefile_hwp_bodytext`, `pypdf_extract_text` |
| `raw_char_len` | 원문 추출 직후 글자 수입니다. |
| `clean_char_len` | artifact 정제 후 글자 수입니다. |
| `v1_text_blocks`, `v2_table_blocks` | 문서별 block 수입니다. |
| `v1_chunks`, `v2_chunks` | 문서별 chunk 수입니다. |
| `budget_candidate_count` | 사업금액 후보 수입니다. |
| `date_candidate_count` | 날짜 후보 수입니다. |
| `period_candidate_count` | 기간 후보 수입니다. |
| `eligibility_candidate_count` | 입찰참가자격 후보 수입니다. |
| `submission_doc_candidate_count` | 제출서류 후보 수입니다. |
| `final_submission_doc_count` | 최종 제출서류 후보 수입니다. |
| `final_notice_id`, `notice_id_status` | 최종 공고번호와 상태입니다. |
| `final_budget`, `final_budget_krw`, `final_budget_status` | 최종 사업금액 관련 값입니다. |
| `final_published_at`, `final_bid_start`, `final_bid_deadline` | 최종 날짜 추출값입니다. |
| `final_project_duration`, `final_maintenance_period`, `final_warranty_period` | 최종 기간 추출값입니다. |
| `final_deadline_terms` | 기타 기한/기간 표현입니다. |
| `final_bid_eligibility_terms` | 최종 입찰참가자격 관련 문장입니다. |

## 12. parsing_summary.json 주요 key

| key | 설명 |
|---|---|
| `output_description` | P2 산출물 설명입니다. |
| `parsing_output_name` | 산출물 폴더명입니다. 예: `parsing_p2_250` |
| `parsing_version_label` | 파싱 버전 라벨입니다. |
| `pilot_total_docs` | pilot 문서 수입니다. 현재 250입니다. |
| `eval_ground_truth_docs_total` | eval 정답 문서 수입니다. 현재 62입니다. |
| `eval_docs_included` | pilot에 포함된 eval 문서 수입니다. |
| `additional_sampled_docs` | eval 문서 외 추가 샘플링 문서 수입니다. |
| `hwp_docs`, `pdf_docs` | 파일 형식별 문서 수입니다. |
| `parse_success_docs`, `parse_failed_docs` | 파싱 성공/실패 문서 수입니다. |
| `v1_text_blocks`, `v2_table_blocks` | block 생성 수입니다. |
| `v1_chunks`, `v2_chunks` | chunk 생성 수입니다. |
| `docs_with_final_budget` | 최종 사업금액이 추출된 문서 수입니다. |
| `docs_with_final_project_duration` | 최종 사업기간이 추출된 문서 수입니다. |
| `docs_with_final_bid_eligibility_terms` | 최종 입찰참가자격이 추출된 문서 수입니다. |
| `docs_with_final_submission_documents` | 최종 제출서류가 추출된 문서 수입니다. |
| `notice_id_status_counts` | 공고번호 상태별 집계입니다. |
| `budget_status_counts` | 사업금액 상태별 집계입니다. |
| `artifact_remove_tokens` | 제거 대상으로 확정한 artifact 문자 목록입니다. |
| `confirmed_keep_hanja_tokens` | 보존 대상으로 확정한 한자 목록입니다. |
| `keep_hanja_runs` | 보존 대상으로 확정한 한자 조합 목록입니다. |
| `chunk_max_chars`, `chunk_overlap` | 청킹 설정입니다. |

## 13. Retrieval 사용 시 기본 원칙

1. 기본 corpus는 `chunks_v2.jsonl`을 사용합니다.
2. baseline 비교가 필요할 때만 `chunks_v1.jsonl`을 함께 사용합니다.
3. Chroma 적재 전 아래 조건으로 필터링합니다.

```python
embed_chunks = chunks[
    chunks['embed_enabled'].fillna(True).astype(bool)
    & chunks['chunk_type'].astype(str).ne('toc')
    & chunks['content'].fillna('').astype(str).str.strip().ne('')
].copy()
```

4. Chroma metadata에는 list/dict 타입을 그대로 넣지 말고, 필요한 컬럼만 문자열/숫자로 변환해서 넣는 것을 권장합니다.
5. `final_*` key는 검색 결과 해석, reranker 분석, UI 표시 후보에 활용합니다.
6. `*_candidates`는 넓게 잡은 후보입니다. 최종 응답 근거로 사용할 때는 evidence와 원문 chunk를 함께 확인합니다.
