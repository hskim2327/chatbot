# parsing_p4_hwpx_125_0521 JSON Key 설명서

이 문서는 `parsing_p4_hwpx_125_0521` 산출물의 JSON/JSONL key를 설명합니다.

- corpus_name: `p4_hwpx_125`
- corpus_version: `v2_hwpx_precision_fact_table_aware`
- parser_version: `p4_hwpx_precision_v2026_05_21`
- 기본 retrieval 파일: `chunks_v2_125.jsonl`
- baseline 비교 파일: `chunks_v1_125.jsonl`
- source 원문 조회 파일: `source_store_125.jsonl`
- 문서 수: 125개
- eval 정답 문서 포함 수: 40개
- 추가 선별 문서 수: 85개

`jsonl`은 한 줄에 JSON 객체 하나가 들어가는 형식입니다. 파일 전체가 하나의 JSON 배열이 아니라 각 줄이 독립적인 record입니다.

## 1. 대상 파일

| 파일 | 단위 | 설명 |
|---|---:|---|
| `chunks_v2_125.jsonl` | chunk | 기본 retrieval corpus입니다. text/table/fact 후보를 포함합니다. |
| `chunks_v1_125.jsonl` | chunk | clean text baseline입니다. table/fact 개선 효과 비교에 사용합니다. |
| `source_store_125.jsonl` | source block | v2 chunk의 긴 원문/표 구조 조회용 파일입니다. Chroma에 그대로 넣지 않습니다. |
| `source_store_v1_125.jsonl` | source block | v1 baseline chunk의 원문 조회용 파일입니다. |
| `metadata_light_125.xlsx` | document | 문서별 파싱 결과, 최종 추출값, G2B 매칭 상태를 요약한 엑셀입니다. |
| `pilot_docs_125.csv` | document | 125개 문서 선택 결과와 eval/filler 구분 정보입니다. |
| `manifest.json` | summary | corpus 구성 규칙, parser version, hash, 파일명을 기록합니다. |
| `validation_report.json` | summary | v2 corpus 검증 결과입니다. |

## 2. Chroma 적재 매핑

```python
collection.add(
    ids=[record["chunk_id"]],
    documents=[record["content"]],
    metadatas=[record["metadata"]],
)
```

| P4 JSONL key | Chroma 입력 | 설명 |
|---|---|---|
| `chunk_id` | `ids` | Chroma 고유 ID입니다. 중복되면 안 됩니다. |
| `content` | `documents` | 실제 임베딩/검색에 사용할 chunk 본문입니다. |
| `metadata` | `metadatas` | 필터링, 출처 표시, 분석에 필요한 짧은 scalar metadata입니다. |

## 3. chunks_v2_125.jsonl 최상위 key

| key | 설명 |
|---|---|
| `chunk_id` | chunk 고유 ID입니다. |
| `doc_id` | 파일명 기반 내부 문서 ID입니다. |
| `doc_key` | 확장자와 일부 표기 차이를 줄인 문서 식별명입니다. |
| `source_file` | 원본 파일명입니다. |
| `source_format` | 실제 파싱에 사용된 형식입니다. 예: `hwpx`, `pdf`, `hwp_fallback` |
| `chunk_type` | chunk 종류입니다. 예: `text`, `table`, `fact_candidates`, `toc` |
| `embed_enabled` | 기본 임베딩 대상 여부입니다. `false`면 Chroma 적재에서 제외합니다. |
| `content` | 임베딩할 검색용 텍스트입니다. |
| `metadata` | Chroma metadata로 넣기 좋은 짧은 dict입니다. |
| `source_ref` | 긴 원문 또는 표 구조를 `source_store_125.jsonl`에서 찾기 위한 참조 dict입니다. |
| `fact_type` | `chunk_type='fact_candidates'`일 때 fact 목적을 나타냅니다. |
| `fact_status` | fact 추출 상태입니다. |
| `fact_confidence` | fact 신뢰도입니다. low-confidence fact는 기본적으로 embed 대상에서 제외합니다. |
| `evidence_text_short` | fact 판단의 짧은 근거 문장입니다. |

## 4. chunk_type 값

| chunk_type | row 수 | 설명 |
|---|---:|---|
| `text` | 5795 | 일반 본문 문단 기반 chunk입니다. |
| `table` | 15598 | HWPX/PDF에서 추출한 표 기반 chunk입니다. |
| `fact_candidates` | 959 | 문서 전체에서 뽑은 핵심 정보 chunk입니다. |
| `toc` | 56 | 목차/구조용 chunk입니다. 기본 검색에서는 제외합니다. |

## 5. fact_type 값

| fact_type | row 수 | 설명 |
|---|---:|---|
| `document_summary` | 216 | 문서명, alias, 발주기관, 사업유형, 예산/기간/마감/제출/자격 신호를 모은 요약 chunk입니다. |
| `budget` | 102 | 사업금액/사업비/예산/기초금액/미기재 예산 상태 관련 chunk입니다. |
| `duration` | 118 | 사업기간/수행기간/계약기간/유지보수기간 관련 chunk입니다. |
| `bid_deadline` | 49 | 입찰마감일/제출마감 관련 chunk입니다. |
| `submission_documents` | 113 | 제출서류명 관련 chunk입니다. |
| `submission_logistics` | 118 | 제출방법/제출장소/제출처 관련 chunk입니다. |
| `eligibility` | 118 | 입찰참가자격/자격요건/공동수급/실적 관련 chunk입니다. |
| `business_type` | 125 | 구축/운영/유지관리/고도화/보안/클라우드 등 사업유형 후보 chunk입니다. |

## 6. metadata 내부 key

| key | 설명 |
|---|---|
| `doc_id`, `doc_key`, `source_file`, `source_format` | 문서 식별과 출처 표시용 기본값입니다. |
| `chunk_type`, `section_path`, `section_type` | chunk 종류와 문서 내 위치입니다. |
| `issuer`, `project_name` | 발주기관과 사업명 후보입니다. |
| `g2b_notice_id`, `g2b_bid_deadline` | G2B에서 보수적으로 병합한 공고번호와 입찰마감일시입니다. 게시일자는 사용하지 않습니다. |
| `fact_type`, `fact_status`, `fact_confidence` | fact chunk 분석용 key입니다. |
| `table_role`, `table_signal_score`, `table_embed_reason` | table chunk의 검색 가치 판단 결과입니다. |

## 7. 새로 강화된 key

| key | 설명 |
|---|---|
| `notice_base_amount` | `기초금액`, `예정가격`, `추정가격`처럼 실제 사업예산과 분리해야 하는 조달 기준 금액입니다. |
| `budget_missing_reason` | 예산이 미기재/비공개/문서상 미포함일 때 사유를 기록합니다. |
| `budget_value_role` | 금액의 역할입니다. 예: `actual_project_budget`, `notice_base_amount`, `symbolic_notice_base_amount`, `missing_budget` |
| `project_family_key` | 재공고/원공고/유사 공고를 분석할 때 쓰는 문서 family key입니다. 병합 key가 아니라 관계 확인용입니다. |
| `notice_prefix_flags` | 파일명/사업명에서 감지한 접두어 flag입니다. 예: `reannouncement`, `urgent`, `fingerprint`, `international` |
| `is_reannouncement` | 재공고/재입찰 계열 여부입니다. |
| `aliases` | 원문 파일명, 정규화명, 접두어 제거명, 공백/괄호 제거명을 묶은 검색 보강 alias 문자열입니다. |

## 8. source_store_125.jsonl key

| key | 설명 |
|---|---|
| `source_store_id` | chunk의 `source_ref.source_store_id`와 연결되는 상세 근거 ID입니다. |
| `full_text` | chunk보다 긴 원문 또는 fact/table 원문입니다. |
| `table_structure` | table block일 때 행/열, 병합 셀, row type 등 표 구조 정보입니다. |
| `final_budget`, `notice_base_amount`, `budget_missing_reason` | 문서 단위 예산 판단 결과입니다. |
| `final_bid_deadline`, `g2b_bid_deadline` | 원문/G2B 기준 입찰마감일시입니다. 게시일자는 사용하지 않습니다. |

주의: `source_store`는 크기가 크고 GitHub 업로드 대상이 아닙니다. 검색 UI나 정성 분석에서 원문 근거를 확인할 때만 사용합니다.

## 9. 예산 정책 요약

- `final_budget`은 실제 사업예산으로 볼 수 있는 금액만 사용합니다.
- `기초금액`, `예정가격`, `추정가격` 단독 문맥은 `final_budget`이 아니라 `notice_base_amount`로 분리합니다.
- `1원`, `0원`, 소액 금액은 실제 사업예산으로 쓰지 않습니다.
- `미기재`, `비공개`, `사업예산 미포함`은 `budget_missing_reason`으로 남깁니다.

## 10. 적재 시 필수 필터

```python
if record.get("embed_enabled") is not True:
    continue
if record.get("chunk_type") == "toc":
    continue
if not str(record.get("content", "")).strip():
    continue
```
