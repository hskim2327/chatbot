# P4 HWPX 690 JSON Key 설명서

이 문서는 `outputs/parsing_p4_hwpx_690` 산출물 중 Chroma 적재에 직접 사용하는 `chunks_v2_690.jsonl`의 주요 key를 설명합니다.

- corpus_name: `p4_hwpx_690`
- corpus_version: `v2_hwpx_table_aware`
- 기본 retrieval 파일: `chunks_v2_690.jsonl`
- baseline 비교 파일: `chunks_v1_690.jsonl`
- 참고 메타데이터 파일: `metadata_light_690.xlsx`

`jsonl`은 한 줄에 JSON 객체 하나가 들어가는 형식입니다. 파일 전체가 하나의 JSON 배열이 아니라, 각 줄이 독립적인 chunk record입니다.

## 핵심 구조

P4의 핵심은 Chroma에 바로 넣기 쉬운 구조입니다.

```text
chunk_id  -> Chroma ids
content   -> Chroma documents
metadata  -> Chroma metadatas
```

즉, 선생님이 설명해주신 “청크 텍스트와 메타데이터를 함께 내장하는 방식”은 아래처럼 적용됩니다.

```python
collection.add(
    ids=[record["chunk_id"]],
    documents=[record["content"]],
    metadatas=[record["metadata"]],
)
```

단, 실제 예시 코드에서는 KoE5 임베딩을 직접 만들기 때문에 `embeddings`도 함께 넣습니다.

```python
collection.add(
    ids=ids,
    documents=documents,
    metadatas=metadatas,
    embeddings=embeddings,
)
```

## 1. 최상위 key

| key | 타입 | 설명 | Chroma 매핑 |
|---|---|---|---|
| `chunk_id` | string | chunk 고유 ID입니다. Chroma의 `ids`로 사용합니다. 중복되면 안 됩니다. | `ids` |
| `doc_id` | string | 문서 고유 ID입니다. 파일명 기반 hash로 만들어져 250/690 확장에서도 안정적으로 유지됩니다. | metadata에도 포함 |
| `doc_key` | string | 평가 데이터와 매칭하기 위한 canonical 문서명입니다. 확장자/공백/기호 차이를 줄인 이름입니다. | metadata에도 포함 |
| `source_file` | string | 원본 파일명입니다. 검색 결과 출처 표시의 기본값입니다. | metadata에도 포함 |
| `chunk_type` | string | chunk 종류입니다. 예: `text`, `table`, `fact_candidates`, `toc` | metadata에도 포함 |
| `embed_enabled` | bool | 기본 임베딩 대상 여부입니다. `false`면 Chroma 적재에서 제외합니다. | 적재 필터 |
| `content` | string | 실제 임베딩할 검색용 텍스트입니다. Chroma의 `documents`에 들어갑니다. | `documents` |
| `metadata` | object | Chroma filter/source 표시용 메타데이터입니다. scalar 중심으로 구성합니다. | `metadatas` |
| `source_ref` | object | 상세 근거 위치를 찾기 위한 참조 정보입니다. Chroma에는 `source_store_id` 같은 연결 key만 metadata로 넣습니다. | metadata 일부 |

## 2. chunk_type

| chunk_type | 설명 | 기본 임베딩 여부 | 사용 목적 |
|---|---|---:|---|
| `text` | 표가 아닌 일반 본문 문단입니다. | true | 일반 질의 검색의 기본 근거 |
| `table` | HWPX/PDF에서 추출한 표 기반 텍스트입니다. | true | 예산, 제출서류, 평가기준, 요구사항처럼 표 안에 있는 정보 검색 |
| `fact_candidates` | 사업금액, 사업기간, 제출서류, 입찰참가자격, 입찰마감일 등 핵심 후보 정보를 짧게 모은 검색 보조 chunk입니다. | true 또는 false | 핵심 필드성 질문 검색 보강 |
| `toc` | 목차 정보입니다. | false | 문서 구조 파악용으로 보존하지만 기본 검색에서는 제외 |

주의: `toc`는 구조 파악에는 유용하지만 검색 결과 상위권에 올라오면 실제 답변 근거로 약할 수 있어 기본 Chroma 적재에서는 제외합니다.

## 3. metadata 주요 key

`metadata`는 Chroma의 `metadatas`에 들어갑니다. Chroma metadata는 필터링과 출처 표시에 쓰는 것이 목적이므로 긴 원문, 중첩 dict/list, 표 전체 JSON은 넣지 않습니다.

| key | 설명 |
|---|---|
| `doc_id` | 문서 고유 ID입니다. |
| `doc_key` | 평가 데이터 매칭용 정규화 문서명입니다. |
| `source_file` | 원본 파일명입니다. |
| `chunk_type` | `text`, `table`, `fact_candidates`, `toc` 중 하나입니다. |
| `section_path` | chunk가 속한 장/절/구획 경로입니다. 없으면 빈 값일 수 있습니다. |
| `block_id` | 파싱 단계의 block 식별자입니다. |
| `table_id` | 표 chunk일 때 표 식별자입니다. |
| `row_type` | 표 행의 성격입니다. 예: `header`, `body`, `section`, `mixed` 등. |
| `row_group` | 병합 셀이나 상위 구분값이 이어지는 표에서 같은 의미 묶음을 표시하기 위한 값입니다. |
| `issuer` | 발주기관 또는 수요기관 후보입니다. |
| `project_name` | 사업명 후보입니다. |
| `source_format` | 실제 파싱에 사용한 형식입니다. 예: `hwpx`, `pdf`, `hwp_fallback`. |
| `notice_id_final` | 최종 공고번호 후보입니다. G2B 보강 정보가 있으면 우선 반영합니다. |
| `notice_round_final` | 공고 차수입니다. 공고번호 뒤 차수 정보가 있을 때 분리합니다. |
| `bid_deadline_final` | 최종 입찰마감일시 후보입니다. |
| `g2b_match_status` | G2B 보강 매칭 상태입니다. 예: `matched_high`, `matched_needs_review`, `candidate_only`, `unmatched`. |
| `g2b_match_score` | G2B 매칭 점수입니다. |
| `fact_type` | `fact_candidates` chunk에서 어떤 정보 유형인지 나타냅니다. |
| `fact_status` | 핵심 후보 추출 상태입니다. 예: `extracted`, `needs_review`. |
| `fact_confidence` | 후보 정보 신뢰도입니다. 예: `high`, `medium`, `low`. |
| `source_store_id` | 상세 근거 파일과 연결할 수 있는 key입니다. Chroma 검색 결과에서 원문 근거를 더 찾아야 할 때 사용합니다. |

## 4. table 관련 key

P4는 HWPX를 사용해 표를 더 안정적으로 분리합니다. 다만 모든 표가 완벽한 행/열 구조를 갖는 것은 아니므로, 표 정보를 너무 복잡하게 metadata에 넣지 않고 검색 가능한 텍스트와 최소 연결 정보 중심으로 둡니다.

| key | 설명 |
|---|---|
| `table_id` | 같은 표에서 나온 chunk를 묶기 위한 ID입니다. |
| `row_type` | 해당 행이 header인지, body인지, section 구분 행인지 표시합니다. |
| `row_group` | 병합 셀 또는 상위 구분값이 여러 행에 걸쳐 적용될 때 같은 그룹으로 묶기 위한 값입니다. |
| `section_path` | 표가 위치한 문서 구획입니다. 예: `제안요청사항`, `평가 기준`, `제출 서류`. |
| `content` | 표 원문을 검색에 유리한 문장형/행 단위 텍스트로 변환한 값입니다. |

### row_type 예시

```text
header  : "평가항목 | 평가방법 | 배점"처럼 컬럼명을 담은 행
body    : 실제 데이터가 들어있는 일반 행
section : "1차년도 구축 예정 장비"처럼 표 내부의 구획 제목 행
mixed   : header/body 성격이 섞여 자동 판단이 애매한 행
```

### row_group 예시

아래처럼 왼쪽 셀이 병합되어 여러 행에 걸친 경우가 있습니다.

```text
구분      | 세부시설 | 면적
센터 1층 | 기계실   | 48.1㎡
센터 1층 | 발전실   | 48.1㎡
센터 1층 | 전기실   | 48.1㎡
```

이때 `row_group`은 `센터 1층`처럼 여러 행을 묶는 상위 구분값을 보존하는 데 사용합니다. 검색 결과에서 특정 행 하나만 보더라도 어느 상위 구분에 속하는지 알 수 있게 하려는 목적입니다.

## 5. source_ref

`source_ref`는 Chroma에 직접 넣는 긴 원문이 아닙니다. 검색 결과가 나온 뒤 더 긴 근거를 찾아야 할 때 연결할 수 있는 참조 정보입니다.

| key | 설명 |
|---|---|
| `source_store_id` | 상세 근거 저장소와 연결되는 ID입니다. |
| `block_id` | 원문 block 위치입니다. |
| `part_index` | 긴 block이 여러 chunk로 나뉘었을 때 몇 번째 part인지 나타냅니다. |
| `content_hash` | content 변경 여부를 추적하기 위한 hash입니다. |

P4 기본 generation은 Chroma가 반환한 `documents + metadatas`만으로도 가능합니다. `source_ref`는 표 원형, 긴 근거, 정성평가용 원문 확인이 필요할 때만 추가로 사용합니다.

## 6. metadata_light_690.xlsx 주요 컬럼

`metadata_light_690.xlsx`는 사람이 검토하기 위한 참고 파일입니다. Chroma 적재 입력이 아닙니다.

| 컬럼 | 설명 |
|---|---|
| `source_file` | 원본 파일명 |
| `source_format` | 파싱 형식: `hwpx`, `pdf`, `hwp_fallback` |
| `project_name` | 사업명 후보 |
| `issuer` | 기관명 후보 |
| `final_budget` | 사업금액 후보 |
| `final_project_duration` | 사업기간 후보 |
| `notice_id_final` / `공고번호` | 공고번호 후보 |
| `notice_round_final` / `공고차수` | 공고 차수 |
| `bid_deadline_final` / `입찰마감일시` | 입찰마감일시 후보 |
| `final_submission_documents` | 제출서류 후보 |
| `final_bid_eligibility_terms` | 입찰참가자격 후보 |
| `g2b_match_status` | G2B 매칭 상태 |
| `text_preview_5000` | 정성 확인용 본문 미리보기 |

## 7. Chroma 적재 시 필수 필터

```python
if record.get("embed_enabled") is not True:
    continue
if record.get("chunk_type") == "toc":
    continue
if not str(record.get("content", "")).strip():
    continue
```

이 조건을 지켜야 불필요한 목차, 빈 content, 검토 제외 chunk가 Chroma에 들어가지 않습니다.

## 8. 금지하거나 피해야 할 사용

| 항목 | 이유 |
|---|---|
| metadata에 긴 원문 넣기 | Chroma metadata가 무거워지고 필터링이 불안정해집니다. |
| metadata에 rows/list/dict 그대로 넣기 | 환경에 따라 저장/필터링 재현성이 떨어집니다. |
| `source_store_690.jsonl`을 Chroma에 그대로 넣기 | 검색용이 아니라 상세 근거 확인용이라 DB가 매우 무거워집니다. |
| `.npy` cache를 기본 산출물처럼 공유하기 | corpus/model/chunk 순서가 바뀌면 재사용이 위험합니다. |
| `git add .` | 원본 데이터, Chroma DB, cache가 함께 올라갈 수 있습니다. |

## 9. 요약

P4 690의 기본 원칙은 아래와 같습니다.

```text
Chroma에는 찾기 좋은 content와 가벼운 metadata를 넣는다.
긴 원문과 표 원형은 필요할 때만 source_ref로 따라간다.
chunk_id, doc_id, doc_key를 안정적으로 유지해 평가/검색/근거 확인을 연결한다.
```

