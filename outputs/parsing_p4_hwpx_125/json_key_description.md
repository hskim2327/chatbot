# parsing_p4_hwpx_125 JSON Key 설명서

이 문서는 `outputs/parsing_p4_hwpx_125` 산출물의 JSON/JSONL key를 정리한 문서입니다.

- corpus_name: `p4_hwpx_125`
- corpus_version: `v2_hwpx_precision_fact_table_aware`
- baseline_version: `v1_clean_text`
- parser_version: `p4_hwpx_precision_v2026_05_20`
- 기본 retrieval 파일: `chunks_v2_125.jsonl`
- baseline 비교 파일: `chunks_v1_125.jsonl`
- source 원문 조회 파일: `source_store_125.jsonl`
- 문서 수: 125개
- eval 정답 문서 포함 수: 40개
- 추가 선별 문서 수: 85개
- eval scope: 중복 제거 후 `eval_batch_01~25`, 500문항 기준

`jsonl`은 한 줄에 JSON 객체 하나가 들어가는 형식입니다. 파일 전체가 하나의 JSON 배열이 아니라, 각 줄이 독립적인 record입니다.

## P4 HWPX 125에서 달라진 점

| 항목 | 변경 내용 |
|---|---|
| 문서 구성 | eval 정답 문서 40개를 먼저 포함하고, 사업유형/발주기관/유사 사업명/재공고 계열을 고려해 filler 85개를 추가했습니다. |
| HWPX 재파싱 | 기존 690 결과를 단순 필터링하지 않고, 선택된 125개 문서를 개선된 파서로 다시 파싱했습니다. |
| `document_summary` | 문서명, 사업명 alias, 발주기관, 사업유형, 예산/기간/마감/제출/자격 핵심 신호를 한 청크에 모은 요약 fact chunk입니다. |
| fact chunk 분리 | 예산, 기간, 입찰마감, 제출서류, 제출방법/장소, 자격요건, 사업유형을 목적별 fact chunk로 분리했습니다. |
| table gating | 평가기준/제출서류/요구사항/사업범위/자격/예산/기간 관련 표는 살리고, 표지/목차/빈 셀 위주의 약한 표는 `embed_enabled=false`로 낮췄습니다. |
| `source_store` 분리 | Chroma metadata에는 짧은 값만 넣고, 긴 원문과 표 구조는 `source_store_125.jsonl`에서 `source_store_id`로 조회합니다. |
| G2B 병합 | 공고번호와 입찰마감일시는 보수적으로 병합합니다. 날짜는 입찰마감일시만 사용하고 게시일자는 사용하지 않습니다. |
| 예산 정책 | `final_budget`은 실제 사업예산으로 볼 수 있는 금액만 올립니다. `1원` 같은 상징 기초금액이나 미기재 `0원`은 일반 사업예산으로 취급하지 않습니다. |

## 대상 파일

| 파일 | 단위 | 설명 |
|---|---:|---|
| `chunks_v2_125.jsonl` | chunk | 기본 retrieval corpus입니다. text/table/fact 후보를 포함합니다. |
| `chunks_v1_125.jsonl` | chunk | clean text baseline입니다. table/fact 개선 효과 비교에 사용합니다. |
| `source_store_125.jsonl` | source block | v2 chunk의 긴 원문/표 구조 조회용 파일입니다. Chroma에 그대로 넣지 않습니다. |
| `source_store_v1_125.jsonl` | source block | v1 baseline chunk의 원문 조회용 파일입니다. |
| `metadata_light_125.xlsx` | document | 문서별 파싱 결과, 최종 추출값, G2B 매칭 상태를 요약한 엑셀입니다. |
| `pilot_docs_125.csv` | document | 125개 문서 선택 결과와 eval/filler 구분 정보입니다. |
| `table_preview_125.csv` | table preview | table chunk 품질을 사람이 빠르게 확인하기 위한 미리보기 CSV입니다. |
| `manifest.json` | summary | corpus 구성 규칙, selection 결과, parser version, table/G2B 정책을 기록합니다. |
| `validation_report.json` | summary | v2 corpus 검증 결과입니다. |
| `validation_report_v1.json` | summary | v1 baseline 검증 결과입니다. |

## 1. chunks_v2_125.jsonl 최상위 key

`chunks_v2_125.jsonl`은 Chroma 적재의 기본 입력입니다. `embed_enabled == true`인 row만 기본 임베딩 대상으로 사용합니다.

| key | 설명 |
|---|---|
| `chunk_id` | chunk 고유 ID입니다. 문서 ID, chunk type, block 번호, part 번호, content hash를 포함합니다. |
| `doc_id` | 파일명 기반 내부 문서 ID입니다. 예: `doc_2ee3f5efecd4` |
| `doc_key` | 확장자와 일부 표기 차이를 줄인 문서 식별명입니다. |
| `source_file` | 원본 파일명입니다. HWP/HWPX 파일명은 유니코드 정규화 형태가 다를 수 있습니다. |
| `source_format` | 파싱에 사용된 원본 형식입니다. 예: `hwpx`, `pdf` |
| `chunk_type` | chunk 종류입니다. 예: `text`, `table`, `fact_candidates`, `toc` |
| `embed_enabled` | 기본 임베딩 대상 여부입니다. `false`면 source_store에는 보존하지만 Chroma 적재에서는 제외하는 것을 권장합니다. |
| `content` | 실제 임베딩/검색에 사용할 chunk 본문입니다. |
| `metadata` | Chroma metadata로 넣기 좋은 짧은 dict입니다. list/dict 원문이나 긴 표 구조는 넣지 않습니다. |
| `source_ref` | 긴 원문 또는 표 구조를 `source_store_125.jsonl`에서 다시 찾기 위한 참조 dict입니다. |
| `fact_type` | `chunk_type='fact_candidates'`일 때 fact 목적을 나타냅니다. |
| `fact_status` | fact 추출 상태입니다. 현재 v2 검증 기준 대부분 `extracted`입니다. |
| `fact_confidence` | fact 신뢰도입니다. 예: `high`, `medium`. low-confidence fact는 기본적으로 embed 대상에서 제외하는 정책입니다. |
| `evidence_text_short` | fact 판단의 짧은 근거 문장입니다. 긴 근거는 `source_store`에서 확인합니다. |

## 2. chunk_type 값

| 값 | 설명 | 기본 embed 여부 |
|---|---|---:|
| `text` | 원문 문단 기반 본문 chunk입니다. | true |
| `table` | HWPX/PDF에서 추출한 표 기반 chunk입니다. 표 섹션, 컬럼, row_group 정보가 content 앞부분에 포함됩니다. | 신호가 강하면 true |
| `fact_candidates` | 문서 전체에서 뽑은 핵심 정보 chunk입니다. `fact_type`으로 목적을 구분합니다. | 신뢰도가 충분하면 true |
| `toc` | 목차 chunk입니다. 구조 파악용으로 보존하지만 기본 검색에서는 제외합니다. | false |

v2 현재 검증 기준 row 수는 아래와 같습니다.

| chunk_type | row 수 |
|---|---:|
| `text` | 5,795 |
| `table` | 15,598 |
| `fact_candidates` | 892 |
| `toc` | 56 |

## 3. fact_type 값

`fact_candidates`는 하나의 큰 fact block이 아니라 검색 목적별로 나뉜 핵심 청크입니다.

| fact_type | 설명 | 주요 질문 예시 |
|---|---|---|
| `document_summary` | 문서명, 사업명 alias, 발주기관, 사업유형, 주요 예산/기간/마감/제출/자격 신호를 짧게 모은 문서 요약 청크입니다. | "이 사업 문서 찾아줘", "두 사업 비교해줘" |
| `budget` | 사업금액/사업비/예산/추정가격/배정예산 관련 청크입니다. | "예산이 얼마야?", "사업비 비교" |
| `duration` | 사업기간/수행기간/계약기간/유지보수기간 관련 청크입니다. | "사업기간은?", "유지보수 기간은?" |
| `bid_deadline` | 입찰마감일/제출마감/접수마감 관련 청크입니다. | "입찰 마감일은?" |
| `submission_documents` | 제안서, 발표자료, 사업자등록증 등 제출서류명 관련 청크입니다. | "제출서류는 뭐야?" |
| `submission_logistics` | 제출방법, 제출장소, 제출처, 온라인/방문 제출 관련 청크입니다. | "어디로 제출해?", "방문 제출이야?" |
| `eligibility` | 입찰참가자격, 자격요건, 공동수급, 실적, 인증 관련 청크입니다. | "참가자격은?" |
| `business_type` | 구축/운영/유지관리/고도화/보안/클라우드 등 사업유형 후보 청크입니다. | "사업유형이 뭐야?" |

v2 현재 검증 기준 fact row 수는 아래와 같습니다.

| fact_type | row 수 |
|---|---:|
| `document_summary` | 147 |
| `budget` | 104 |
| `duration` | 118 |
| `submission_documents` | 113 |
| `submission_logistics` | 118 |
| `eligibility` | 118 |
| `business_type` | 125 |
| `bid_deadline` | 49 |

주의: 위 수는 문서 수가 아니라 chunk row 수입니다. 긴 fact content가 part로 나뉘면 한 문서에서 2개 이상 row가 생길 수 있습니다.

## 4. metadata 내부 key

`metadata`는 Chroma metadata로 넣기 위한 짧은 필드만 담습니다.

| key | 설명 |
|---|---|
| `doc_id` | 내부 문서 ID입니다. |
| `doc_key` | 문서 식별용 key입니다. |
| `source_file` | 원본 파일명입니다. |
| `source_format` | 파싱 형식입니다. 예: `hwpx`, `pdf` |
| `file_type` | 원본 파일 확장자 계열입니다. 예: `hwp`, `pdf` |
| `chunk_type` | chunk 종류입니다. |
| `section_path` | 문서 내 섹션 경로입니다. v2에서는 Chroma 호환을 위해 문자열로 저장합니다. |
| `section_type` | RFP 도메인 기준 섹션 분류입니다. 예: `사업개요`, `입찰참가자격`, `핵심 후보 정보` |
| `issuer` | 발주기관명입니다. |
| `project_name` | 사업명 또는 공고명입니다. |
| `g2b_notice_id` | G2B에서 보수적으로 매칭된 공고번호입니다. 매칭 실패/애매하면 빈 값일 수 있습니다. |
| `g2b_bid_deadline` | G2B에서 가져온 입찰마감일시입니다. 게시일자는 사용하지 않습니다. |
| `fact_type` | fact chunk일 때 목적 구분값입니다. |
| `fact_status` | fact 추출 상태입니다. |
| `fact_confidence` | fact 신뢰도입니다. |
| `table_role` | table chunk의 역할 판정입니다. 예: `retrieval_signal`, `weak_table`, `generic_table`, `layout_or_toc` |
| `table_signal_score` | table 검색 신호 점수입니다. 높을수록 검색 가치가 크다고 판단한 표입니다. |
| `table_embed_reason` | table을 embed하거나 suppress한 간단한 이유입니다. |

주의: Chroma metadata에는 list/dict/긴 원문을 그대로 넣지 않는 것이 안전합니다. 긴 근거는 `source_ref.source_store_id`로 `source_store_125.jsonl`에서 조회합니다.

## 5. source_ref 내부 key

| key | 설명 |
|---|---|
| `source_store_id` | `source_store_125.jsonl`의 `source_store_id`와 연결되는 key입니다. |
| `block_id` | chunk가 만들어진 원본 block ID입니다. |
| `part_index` | 하나의 block이 여러 chunk로 쪼개졌을 때 몇 번째 조각인지 나타냅니다. |
| `content_hash` | content 기반 짧은 hash입니다. 중복 추적과 ID 안정화에 사용합니다. |

검색 결과에서 원문을 더 길게 보고 싶으면 `source_ref.source_store_id`를 기준으로 `source_store_125.jsonl`을 조회합니다.

## 6. source_store_125.jsonl key

`source_store_125.jsonl`은 Chroma에 넣지 않는 긴 원문/표 구조/감사 정보를 보존하는 파일입니다.

| key | 설명 |
|---|---|
| `source_store_id` | source block 고유 ID입니다. `chunks_v2_125.jsonl`의 `source_ref.source_store_id`와 연결됩니다. |
| `doc_id`, `doc_key`, `source_file`, `source_format` | 문서 식별 정보입니다. |
| `source_type` | 원본 block 종류입니다. 예: `text`, `table`, `fact_candidates`, `toc` |
| `full_text` | chunk보다 긴 원문 또는 fact/table 원문입니다. |
| `section_path` | 원문 block의 섹션 경로입니다. |
| `block_id` | 원본 block ID입니다. |
| `content_hash` | 원문 content hash입니다. |
| `table_structure` | table block일 때 행/열, 병합 셀, row type 등 표 구조 정보입니다. |
| `final_notice_id` | 원문 또는 G2B 기준 최종 공고번호입니다. 없으면 빈 값입니다. |
| `notice_id_status` | 공고번호 추출 상태입니다. |
| `final_budget` | 원문에서 추출된 최종 사업금액입니다. |
| `final_budget_krw` | 원화 기준 숫자형 금액입니다. |
| `final_budget_status` | 사업금액 추출 상태입니다. |
| `final_project_duration` | 최종 사업기간입니다. |
| `final_bid_deadline` | 최종 입찰마감일입니다. |
| `bid_deadline_status` | 입찰마감일 추출 상태입니다. |
| `g2b_*` | G2B 매칭 상태, 공고번호, 입찰마감일시, 취소공고/애매한 후보 감사 정보입니다. |

주의: `source_store`는 크기가 크고 GitHub 업로드 대상이 아닙니다. 검색 UI나 정성 분석에서 원문 근거를 확인할 때만 사용합니다.

## 7. 사업금액 key

| key | 위치 | 설명 |
|---|---|---|
| `final_budget` | `metadata_light_125.xlsx`, `source_store_125.jsonl` | 최종 사업금액 표현입니다. 예: `11,270,000,000원` |
| `final_budget_krw` | `metadata_light_125.xlsx`, `source_store_125.jsonl` | 원화 기준 숫자형 금액입니다. |
| `final_budget_status` | `metadata_light_125.xlsx`, `source_store_125.jsonl` | 사업금액 상태입니다. 예: `extracted`, `candidate_only`, `missing` |
| `fact_type='budget'` | `chunks_v2_125.jsonl` | 예산 질문에 걸리도록 만든 별도 fact chunk입니다. |
| `evidence_text_short` | `chunks_v2_125.jsonl` | 예산 판단의 짧은 근거입니다. |

주의:

- `final_budget`은 실제 사업예산으로 볼 수 있는 금액만 올립니다.
- `1원`처럼 상징적인 공고 기초금액은 일반 사업예산으로 채택하지 않습니다.
- `미기재(0원)`은 실제 예산 0원이 아니라 미기재/비공개 상태로 해석해야 합니다.
- 예산 질문 평가에서는 `symbolic_1won_budget`, `missing_budget_encoded_as_0won` 같은 별도 태그를 두는 것이 안전합니다.

## 8. 날짜/G2B key

P4 125에서는 날짜 정책을 단순화했습니다. **게시일자는 사용하지 않고, 입찰마감일시만 사용합니다.**

| key | 설명 |
|---|---|
| `final_bid_deadline` | 원문에서 추출한 최종 입찰마감일입니다. |
| `bid_deadline_status` | 입찰마감일 추출 상태입니다. |
| `g2b_bid_deadline` | G2B에서 병합한 입찰마감일시입니다. |
| `g2b_bid_deadline_source` | G2B 입찰마감일시 출처입니다. |
| `g2b_notice_id` | 보수적으로 선택된 G2B 공고번호입니다. |
| `g2b_match_status` | G2B 매칭 상태입니다. 예: `matched_active`, `no_confident_match`, `ambiguous_active` |
| `g2b_match_score` | G2B 제목/기관 매칭 점수입니다. |
| `g2b_conflict_status` | 후보가 서로 충돌하거나 애매한지 기록합니다. |
| `g2b_is_cancelled` | 선택 후보가 취소공고인지 여부입니다. 최종 후보로는 취소공고를 사용하지 않습니다. |
| `g2b_cancelled_notice_ids` | 감사용 취소공고 후보 목록입니다. |
| `g2b_ambiguous_notice_ids` | close match지만 서로 다른 공고번호라 자동 확정하지 않은 후보 목록입니다. |

G2B 병합 정책:

- 취소공고는 감사용으로만 기록하고 최종 공고/마감으로 사용하지 않습니다.
- active 후보가 여러 개이고 서로 다른 공고 base가 근접 점수이면 `ambiguous_active`로 두고 최종 병합을 보수적으로 막습니다.
- 최신성 판단은 게시일자가 아니라 공고 revision suffix, 공고 유형 우선순위, 입찰마감일시를 기준으로 합니다.

## 9. 기간/제출/자격 key

| key | 위치 | 설명 |
|---|---|---|
| `final_project_duration` | `metadata_light_125.xlsx`, `source_store_125.jsonl` | 최종 사업기간입니다. 예: `계약일로부터 24개월 이내` |
| `fact_type='duration'` | `chunks_v2_125.jsonl` | 사업기간/계약기간/유지보수기간 검색용 fact chunk입니다. |
| `final_submission_documents` | `metadata_light_125.xlsx` | 문서별 최종 제출서류 후보를 문자열로 요약한 값입니다. |
| `fact_type='submission_documents'` | `chunks_v2_125.jsonl` | 제출서류명 검색용 fact chunk입니다. |
| `proposal_submission_date_hint` | `metadata_light_125.xlsx` | 제안서 제출일자 후보입니다. |
| `proposal_submission_method_hint` | `metadata_light_125.xlsx` | 제출방법 후보입니다. 예: `방문`, `온라인` |
| `proposal_submission_place_hint` | `metadata_light_125.xlsx` | 제출장소 후보입니다. |
| `fact_type='submission_logistics'` | `chunks_v2_125.jsonl` | 제출방법/제출장소/제출처 검색용 fact chunk입니다. |
| `final_bid_eligibility_terms` | `metadata_light_125.xlsx` | 최종 입찰참가자격 관련 문장 또는 키워드입니다. |
| `fact_type='eligibility'` | `chunks_v2_125.jsonl` | 입찰참가자격/자격요건 검색용 fact chunk입니다. |

주의: `proposal_submission_date_hint`는 후보입니다. 정확한 최종 입찰마감일 판단에는 `final_bid_deadline` 또는 `g2b_bid_deadline`을 우선 확인합니다.

## 10. table 관련 key

P4 125는 table chunk가 많기 때문에 table gating이 중요합니다.

| key | 위치 | 설명 |
|---|---|---|
| `chunk_type='table'` | `chunks_v2_125.jsonl` | 표 기반 chunk입니다. |
| `table_role` | `metadata` | 표의 역할 판정입니다. |
| `table_signal_score` | `metadata` | 검색 신호 점수입니다. |
| `table_embed_reason` | `metadata` | embed/suppress 이유입니다. |
| `table_structure` | `source_store_125.jsonl` | 행/열, 병합 셀, row type 등 표 구조입니다. |

`table_role` 값 예시:

| 값 | 설명 |
|---|---|
| `retrieval_signal` | 평가기준, 제출서류, 요구사항, 사업범위, 자격, 예산/기간 등 검색 가치가 큰 표입니다. |
| `weak_table` | 표이지만 검색 신호가 약해 기본 embed에서 제외될 수 있는 표입니다. |
| `generic_table` | 일반적인 표입니다. |
| `layout_or_toc` | 표지/목차/레이아웃 성격이 강한 표입니다. 기본 embed에서 제외하는 것이 안전합니다. |

현재 v2 검증 기준:

| 항목 | 값 |
|---|---:|
| 전체 table chunk | 15,598 |
| suppress된 table chunk | 3,097 |
| embed 대상 전체 chunk | 19,188 |

## 11. metadata_light_125.xlsx 주요 컬럼

| 컬럼 | 설명 |
|---|---|
| `rank_index` | 125 corpus 내부 순번입니다. |
| `doc_id`, `doc_key`, `norm_name`, `source_file` | 문서 식별 정보입니다. |
| `source_format`, `file_type` | 파싱 형식과 원본 파일 계열입니다. |
| `is_eval_ground_truth` | eval 정답 문서에 포함되는지 여부입니다. |
| `parser_status`, `parser`, `parse_seconds`, `error` | 파싱 성공 여부와 사용 parser, 처리 시간, 오류 정보입니다. |
| `raw_char_len`, `clean_char_len`, `non_table_clean_char_len` | 원문/정제 텍스트 길이입니다. |
| `table_count`, `image_count` | 문서별 표/이미지 수입니다. |
| `project_name`, `issuer` | 사업명과 발주기관입니다. |
| `final_budget`, `final_budget_krw`, `final_budget_status` | 최종 사업금액 관련 값입니다. |
| `final_project_duration` | 최종 사업기간입니다. |
| `final_notice_id`, `notice_id_status` | 최종 공고번호와 추출 상태입니다. |
| `final_bid_deadline`, `bid_deadline_status` | 최종 입찰마감일과 상태입니다. |
| `final_submission_documents` | 최종 제출서류 후보 요약입니다. |
| `final_bid_eligibility_terms` | 입찰참가자격 후보 요약입니다. |
| `business_type_candidates` | 사업유형 후보입니다. |
| `chunk_count_v1`, `chunk_count_v2` | 문서별 v1/v2 chunk 수입니다. |
| `source_store_count_v1`, `source_store_count_v2` | 문서별 source store row 수입니다. |
| `fact_status`, `fact_confidence`, `fact_block_count` | 문서별 fact 생성 상태 요약입니다. |
| `embedded_table_block_count` | embed 대상 table block 수입니다. |
| `suppressed_table_block_count` | suppress된 table block 수입니다. |
| `text_preview_5000` | 정제 원문 앞 5,000자 미리보기입니다. |
| `g2b_*` | G2B 매칭/공고번호/입찰마감/취소공고/애매한 후보 감사 정보입니다. |
| `proposal_submission_date_hint` | 제안서 제출일자 후보입니다. |
| `proposal_submission_method_hint` | 제출방법 후보입니다. |
| `proposal_submission_place_hint` | 제출장소 후보입니다. |

## 12. manifest.json 주요 key

| key | 설명 |
|---|---|
| `corpus_name` | corpus 이름입니다. |
| `corpus_version` | v2 corpus 버전 라벨입니다. |
| `baseline_version` | v1 baseline 버전 라벨입니다. |
| `document_count` | 문서 수입니다. 현재 125입니다. |
| `selection` | eval 포함 수, filler 기준, hard distractor 수, 파일 타입 분포 등 문서 선택 규칙입니다. |
| `parser_version` | 파서 버전입니다. |
| `chunks_v1_file`, `chunks_v2_file` | chunk JSONL 파일명입니다. |
| `source_store_v1_file`, `source_store_v2_file` | source store JSONL 파일명입니다. |
| `chunk_max_chars`, `chunk_overlap` | 청킹 설정입니다. 현재 1000/150입니다. |
| `fact_types` | 생성 대상 fact type 목록입니다. |
| `table_embed_policy` | table embed/suppress 기준입니다. |
| `g2b_merge_policy` | G2B 병합 정책입니다. 게시일자는 사용하지 않고 입찰마감일시만 사용합니다. |
| `github_upload_policy` | GitHub 업로드 제외 대상 정책입니다. |
| `created_at` | corpus 생성 시각입니다. |

## 13. validation_report.json 주요 key

| key | 설명 |
|---|---|
| `status` | 검증 결과입니다. `PASS`면 기본 sanity check를 통과한 상태입니다. |
| `document_count` | 문서 수입니다. |
| `parse_success_docs`, `parse_failed_docs` | 파싱 성공/실패 문서 수입니다. |
| `source_format_counts` | `hwpx`, `pdf` 등 source format별 문서 수입니다. |
| `chunk_count` | chunk row 수입니다. |
| `source_store_count` | source store row 수입니다. |
| `duplicate_doc_id_count` | 중복 문서 ID 수입니다. |
| `duplicate_chunk_id_count` | 중복 chunk ID 수입니다. |
| `duplicate_source_store_id_count` | 중복 source store ID 수입니다. |
| `missing_source_store_ref` | chunk에서 참조하는 source store가 누락된 수입니다. |
| `embed_enabled_count` | 기본 embed 대상 chunk 수입니다. |
| `chunk_type_counts` | chunk type별 row 수입니다. |
| `fact_type_counts` | fact type별 row 수입니다. |
| `low_confidence_fact_embedded_count` | low-confidence fact가 embed 대상에 포함된 수입니다. 0이어야 안전합니다. |
| `table_role_counts` | table role별 row 수입니다. |
| `suppressed_table_chunk_count` | embed에서 제외한 low-signal table chunk 수입니다. |
| `g2b_match_status_counts` | G2B 매칭 상태별 문서 수입니다. |
| `fail_reasons` | 검증 실패 이유 목록입니다. PASS면 빈 list입니다. |

현재 v2 검증 요약:

| 항목 | 값 |
|---|---:|
| `document_count` | 125 |
| `parse_success_docs` | 125 |
| `duplicate_chunk_id_count` | 0 |
| `missing_source_store_ref` | 0 |
| `chunk_count` | 22,341 |
| `embed_enabled_count` | 19,188 |
| `chunks_jsonl_file_size_mib` | 55.14 |
| `status` | PASS |

## 14. Retrieval 사용 시 기본 원칙

1. 기본 corpus는 `chunks_v2_125.jsonl`을 사용합니다.
2. baseline 비교가 필요할 때만 `chunks_v1_125.jsonl`을 함께 사용합니다.
3. Chroma 적재 전 아래 조건으로 필터링합니다.

```python
embed_chunks = chunks[
    chunks["embed_enabled"].fillna(True).astype(bool)
    & chunks["content"].fillna("").astype(str).str.strip().ne("")
].copy()
```

4. `toc`, `weak_table`, `layout_or_toc`는 기본 검색 품질을 떨어뜨릴 수 있으므로 `embed_enabled=false` 정책을 유지합니다.
5. Chroma metadata에는 `metadata` dict의 짧은 값만 넣고, `source_store`, 원본 표 JSON, 긴 OCR 원문은 넣지 않습니다.
6. 검색 결과의 원문 근거를 길게 확인해야 할 때만 `source_ref.source_store_id`로 `source_store_125.jsonl`을 조회합니다.
7. 예산/기간/제출서류/자격요건 질문은 `fact_candidates`가 먼저 잡힐 수 있고, 세부 근거 확인은 본문 `text` 또는 `table` chunk와 함께 보는 것이 안전합니다.
8. multi-doc 질문에서는 `document_summary`가 후보 문서를 넓게 끌어오는 역할을 합니다. 최종 답변 근거는 summary만 보지 말고 원문 chunk를 함께 확인합니다.

## 15. GitHub/공유 시 주의

GitHub에 올려도 되는 파일:

- 코드
- 노트북
- README/guide
- `manifest.json`
- `validation_report.json`
- `validation_report_v1.json`
- 이 설명서

GitHub에 올리지 않는 파일:

- `source_store_125.jsonl`
- `source_store_v1_125.jsonl`
- 원본 HWP/HWPX/PDF
- Chroma DB
- embedding cache

`chunks_v2_125.jsonl`은 공유 목적이면 가능하지만 파일 크기가 크므로, GitHub보다는 Drive/압축 공유가 안전합니다.
