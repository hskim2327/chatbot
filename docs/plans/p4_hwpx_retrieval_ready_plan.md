# P4 HWPX Retrieval-Ready Corpus Plan

## 목적

690개 RFP 전체를 대상으로 HWPX 기반 구조 보존 파싱을 적용한다.

이번 단계의 핵심은 Chroma 적재나 임베딩 실험이 아니라, 다음 단계 실험이 안정적으로 돌아갈 수 있는 retrieval-ready JSONL corpus를 만드는 것이다.

## 현재 결정

- 전체 corpus 기준은 690개다.
- HWPX 변환본이 있는 문서는 HWPX를 우선 사용한다.
- 변환 실패 1개 HWP와 원본 PDF 25개는 fallback 경로로 처리한다.
- 이미지 OCR은 보류한다.
- 표 구조 보존과 파일 용량 제어를 최우선으로 둔다.
- 모든 산출물은 Chroma index payload와 source reference payload로 나눈다.
- 검색과 generation의 기본 입력은 Chroma가 반환하는 `documents + metadatas`다.
- `source_store`는 별도 generation DB가 아니라, 큰 표 구조나 긴 원문 근거를 추가 조회할 때만 사용하는 선택적 상세 근거 저장소다.

## 입력 전략

```text
data/
├─ hwpx_664/          # 변환 성공 HWPX
├─ original_hwp/      # HWPX 변환 실패 파일 fallback
└─ original_pdf/      # 원본 PDF 25개 fallback
```

처리 우선순위:

```text
1. HWPX exists -> HWPX parser
2. PDF original -> PDF parser
3. HWPX missing HWP -> 기존 HWP text extractor or PDF fallback
```

현재 확인된 HWPX 상태:

```text
HWPX converted: 664
HWPX ZIP/XML OK: 664 / 664
docs with tables: 664 / 664
docs with images: 648 / 664
total tables: 84,172
total images: 3,644
missing HWPX: 1
```

## 산출물 분리

P3에서 확인된 가장 큰 리스크는 같은 텍스트와 메타데이터가 여러 파일에 반복 저장되면서 corpus와 cache가 커지는 문제였다.

P4에서는 산출물을 역할별로 분리한다.

```text
Chroma index payload
= collection.add(documents, metadatas, ids)에 바로 들어갈 가벼운 chunk 단위 데이터

Source reference payload
= Chroma 결과만으로 부족할 때 원문/표 구조를 추가 조회하기 위한 선택적 근거 저장소
```

```text
outputs/parsing_p4_hwpx_250/
├─ chunks_v1_250.jsonl
├─ chunks_v2_250.jsonl
├─ source_store_250.jsonl
├─ metadata_light_250.xlsx
├─ manifest.json
├─ validation_report.json
└─ README.md

outputs/parsing_p4_hwpx_500/
...

outputs/parsing_p4_hwpx_690/
...
```

공유 기본 대상:

```text
chunks_v1_*.jsonl
chunks_v2_*.jsonl
metadata_light_*.xlsx
README.md
validation_report.json
```

기본 공유 제외 대상:

```text
source_store_*.jsonl
full parsed source
OCR output
Chroma DB
embedding cache
```

## v1 / v2 정의

| version | 목적 | 설명 |
|---|---|---|
| v1 | baseline | clean text를 일정 길이로 청킹한 비교 기준 |
| v2 | structured retrieval corpus | toc, text, table, fact_candidates를 분리한 구조화 corpus |

v1은 모델링 성능 비교를 위한 기준선이다. v2가 v1보다 좋은지 확인해야 구조화가 실제로 의미 있는지 판단할 수 있다.

## chunks JSONL 구조

`chunks_v*.jsonl`은 Chroma 적재용 retrieval index 파일이다. 원문 보관 파일이 아니다.

Chroma 적재 매핑은 아래처럼 고정한다.

```python
collection.add(
    ids=[row["chunk_id"] for row in chunks],
    documents=[row["content"] for row in chunks],
    metadatas=[row["metadata"] for row in chunks],
)
```

즉 `chunk_id`는 Chroma `ids`, `content`는 Chroma `documents`, `metadata`는 Chroma `metadatas`로 들어간다.

필수 필드:

```json
{
  "chunk_id": "stable chunk id",
  "doc_id": "stable doc id",
  "doc_key": "canonical document key",
  "source_file": "source file name",
  "source_format": "hwpx",
  "chunk_type": "text",
  "embed_enabled": true,
  "content": "text used for embedding",
  "metadata": {
    "doc_id": "stable doc id",
    "doc_key": "canonical document key",
    "source_file": "source file name",
    "source_format": "hwpx",
    "chunk_type": "text",
    "section_path": "사업개요",
    "issuer": "기관명",
    "project_name": "사업명"
  },
  "source_ref": {
    "source_store_id": "source reference id",
    "block_id": "block id",
    "part_index": 1
  }
}
```

반복 저장하지 않을 항목:

```text
full_raw_text
full_table_json
긴 evidence 전문
OCR 전문
final_* 전체 반복
amounts 전체 반복
dates 전체 반복
metadata Excel용 긴 본문
nested dict/list metadata
```

## source_store 구조

`source_store_*.jsonl`은 Chroma metadata의 `source_store_id`로 연결되는 선택적 상세 근거 조회 파일이다.

기본 generation은 Chroma 검색 결과의 `documents + metadatas`를 사용한다. `source_store`는 표 원형, 긴 원문 근거, UI의 원문 보기, 정성평가처럼 Chroma chunk만으로 부족할 때만 조회한다.

```json
{
  "source_store_id": "stable source id",
  "doc_id": "stable doc id",
  "doc_key": "canonical document key",
  "source_file": "source file name",
  "source_type": "table",
  "section_path": "평가 기준",
  "full_text": "source text for human review",
  "table_structure": {},
  "content_hash": "hash"
}
```

Chroma metadata에는 `source_store_id` 같은 연결 key만 넣고, `rows`, `full_table_json`, 긴 원문, OCR 전문은 넣지 않는다.

검증 기준:

```text
missing_source_store_ref = 0
```

## HWPX 표 구조화 전략

HWPX는 ZIP/XML 구조라서 표의 행, 열, 셀 병합 정보를 직접 읽을 수 있다.

활용할 핵심 정보:

```text
rowAddr
colAddr
rowSpan
colSpan
cell text
```

P4 table block은 아래 정보를 가진다.

```json
{
  "table_id": "stable table id",
  "section_path": "제안서 평가",
  "table_shape": {
    "row_count": 10,
    "col_count": 4,
    "cell_count": 32,
    "merged_cell_count": 3
  },
  "columns_candidate": ["평가항목", "평가방법", "배점"],
  "rows": [
    {
      "row_index": 0,
      "row_type": "header_candidate",
      "row_group": null,
      "cells": [
        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "평가항목"}
      ]
    }
  ],
  "body_text": "평가항목: 신인도 | 평가방법: 최근 3년간 부정당업자 제재 여부 | 배점: 2"
}
```

`rows`는 표 원형 보존용이고, `body_text`는 검색과 preview에 쓰기 위한 compact text다.

## row_type / row_group 원칙

표는 항상 깔끔한 header-body 형태가 아니다. 병합 셀, 중간 그룹 제목, 행/열 한쪽만 의미 있는 표가 많다.

`row_type` 후보:

| row_type | 의미 |
|---|---|
| header_candidate | 열 이름으로 볼 가능성이 높은 행 |
| body | 실제 데이터 행 |
| group_title | 여러 행을 묶는 중간 제목 행 |
| note | 주석, 산식, 유의사항 행 |
| blank | 빈 행 또는 의미 없는 구분 행 |
| layout_noise | 표 형태지만 문서 배치용일 가능성이 높은 행 |

`row_group`은 병합 셀이나 중간 제목이 이후 행에 영향을 주는 경우, 그 문맥을 잃지 않기 위한 필드다.

예:

```text
row_group = "센터 지하 1층"
row body = "세부시설: 기계실 | 면적: 48.1m2"
```

이렇게 저장하면 병합된 왼쪽 셀의 의미가 검색용 텍스트에서도 유지된다.

## fact_candidates compact화

`fact_candidates`는 원문 전체 복사본이 아니라 짧은 검색 보조 chunk로 만든다.

대상 정보:

```text
사업금액
사업기간
입찰마감일
제안서 제출 일자
제출 방법
제출 장소
제출서류
입찰참가자격
사업 유형
하자담보책임기간
무상유지보수기간
```

날짜 관련 fact는 입찰마감일을 우선한다. 게시일자/공고일자는 검색 content나 final fact로 사용하지 않는다.

예시:

```json
{
  "chunk_type": "fact_candidates",
  "content": "사업금액: 242,900,000원 | 사업기간: 계약체결일로부터 5개월 | 제출방법: 나라장터 온라인 제출",
  "fact_status": "extracted",
  "fact_confidence": "high",
  "embed_enabled": true,
  "source_ref": {
    "source_store_id": "source id",
    "source_chunk_ids": "related chunk ids"
  },
  "evidence_text_short": "사업기간 : 계약체결일로부터 5개월 / 사업비 : 금242,900,000원"
}
```

오류 강화 방지 규칙:

```text
low confidence fact -> embed_enabled=false
needs_review fact -> embed_enabled=false
계약 후 N일 이내 제출/승인/착수 표현은 사업기간으로 확정하지 않음
사업금액은 사업비/예산/추정금액/배정예산 주변 키워드를 우선함
```

## Budget Semantics And Override Policy

사업금액은 RFP retrieval에서 중요한 key지만, 모든 금액 표현을 같은 의미로 취급하면 안 된다.

특히 아래 두 유형은 일반 `final_budget`으로 넣지 않는다.

```text
1. symbolic placeholder amount
   예: 공고문 기초금액 1원

2. missing budget encoded as zero
   예: 미기재(0원), 명시적 0원 처리
```

### 원칙

`final_budget`은 실제 사업예산 또는 실제 집행 한도로 해석할 수 있는 값만 저장한다.

```text
final_budget = 실제 사업예산
final_budget_krw = 실제 사업예산의 원화 숫자값
final_budget_status = extracted | candidate_only | missing
```

아래 값은 `final_budget`에 넣지 않는다.

```text
1원
0원
미기재(0원)
상징적 기초금액
서식 예시의 1 원 / 2 원
하도급 양식의 번호성 금액
```

전역 small amount 필터는 유지한다.

```text
amount_krw < 1_000_000 -> final_budget 후보에서 제외
```

이 조건을 완화하면 하도급 양식, 서식 번호, 배점, 수량, `1 원`, `2 원` 같은 노이즈가 사업예산으로 승격될 위험이 크다.

### 0원/미기재 처리

`미기재(0원)`은 실제 예산이 0원이라는 뜻이 아니다. 문서 또는 평가셋에서 0원으로 표현되어도 corpus에서는 missing으로 해석한다.

권장 저장 방식:

```text
final_budget = ""
final_budget_krw = ""
final_budget_status = "missing"
budget_missing_reason = "not_disclosed_or_not_specified"
budget_policy_note = "0원은 실제 예산이 아니라 미기재/비공개 표현으로 해석"
```

retrieval content에는 아래처럼 넣을 수 있다.

```text
사업금액/사업비/예산: 미기재 | 비공개 | 문서상 확정 예산 없음
```

단, `사업금액: 0원`처럼 실제 예산으로 오해될 표현은 넣지 않는다.

### 1원/상징 기초금액 처리

일부 공고는 공고문상 기초금액이 `1원`으로 걸려 있지만, 이는 실제 사업예산이 아니라 symbolic placeholder일 수 있다.

이 경우 `final_budget`을 오염시키지 말고 별도 semantic field로 분리한다.

권장 key:

```text
notice_base_amount = "1원"
notice_base_amount_krw = 1
notice_base_amount_status = "symbolic_placeholder"
notice_base_amount_source = "manual_override | g2b_notice | notice_document"
budget_policy_note = "공고문 기초금액은 1원이나 실제 사업예산으로 보지 않음"
```

retrieval content에는 아래처럼 넣는다.

```text
공고문 기초금액/기초금액/상징금액: 1원
실제 사업예산: 미기재 또는 비공개
```

이렇게 하면 `공고문상 기초금액이 얼마인가` 질문에는 대응할 수 있고, 동시에 `사업예산=1원`이라는 잘못된 의미 오염을 막을 수 있다.

### Manual Override는 코드 하드코딩이 아니라 데이터로 관리

특정 문서명을 코드에 직접 쓰는 방식은 금지한다.

금지 예시:

```python
if doc_key == "사단법인 보험개발원_실손보험 청구 전산화 시스템 구축 사업":
    final_budget = "1원"
```

권장 방식은 사람이 검토한 override를 별도 CSV/JSONL로 관리하는 것이다.

권장 파일:

```text
config/manual_overrides/budget_policy_overrides.csv
```

권장 컬럼:

```text
doc_key
source_file
override_type
amount_text
amount_krw
amount_semantics
target_field
evidence
applies_to_eval_ids
reviewer
reviewed_at
note
```

예시:

```text
doc_key = 사단법인 보험개발원_실손보험 청구 전산화 시스템 구축 사업
override_type = notice_base_amount
amount_text = 1원
amount_krw = 1
amount_semantics = symbolic_placeholder
target_field = notice_base_amount
evidence = 공고문상 기초금액은 1원이나 제안요청서상 실제 사업예산은 포함되지 않음
applies_to_eval_ids = Q203|Q209|Q239|Q261
note = final_budget에는 반영하지 않음
```

override 적용 후에도 validation에서 아래를 확인한다.

```text
final_budget_krw < 1_000_000 인 row가 final_budget_status=extracted로 들어오지 않아야 함
notice_base_amount_krw=1 은 final_budget_krw와 분리되어야 함
manual_override_count 기록
manual_override_target_fields 기록
```

### Eval tagging 원칙

예산 질문을 하나의 category로만 평가하지 않는다.

권장 category:

```text
budget_actual
budget_missing
budget_comparison
budget_arithmetic
notice_base_amount_symbolic
```

예:

```text
Q203/Q209/Q239/Q261 -> notice_base_amount_symbolic
미기재(0원) 문항 -> budget_missing
```

일반 예산 성능을 볼 때는 `budget_actual`, `budget_comparison`, `budget_arithmetic`을 우선 보고, `notice_base_amount_symbolic`과 `budget_missing`은 별도 해석한다.

### 더 정석적인 장기 구조

장기적으로는 `budget`을 단일 값이 아니라 typed fact list로 저장하는 것이 가장 안전하다.

예시:

```json
{
  "facts": [
    {
      "fact_name": "budget",
      "value_text": "11,270,000,000원",
      "value_krw": 11270000000,
      "semantics": "actual_project_budget",
      "confidence": "high",
      "source": "rfp_text",
      "evidence_ref": "source_store_id"
    },
    {
      "fact_name": "notice_base_amount",
      "value_text": "1원",
      "value_krw": 1,
      "semantics": "symbolic_placeholder",
      "confidence": "manual_reviewed",
      "source": "manual_override",
      "evidence_ref": "source_store_id or external_notice_ref"
    }
  ]
}
```

typed fact 구조의 장점:

```text
1. 검색용 content와 정답 근거의 의미가 분리됨
2. 같은 금액이라도 실제 예산, 기초금액, 추정가격, 미기재 표현을 구분 가능
3. eval 지표에서 fact_name/semantics별 recall을 계산 가능
4. 사람이 검토한 override와 자동 추출값을 같은 schema로 관리 가능
5. final answer 생성 시 "실제 사업예산"과 "공고문 기초금액"을 혼동하지 않음
```

단기 구현은 `final_budget`을 유지하면서 `notice_base_amount_*`, `budget_missing_reason`, manual override CSV를 추가하는 방식으로 시작하고, 이후 typed fact list로 확장한다.

## 정규화 계획

P4에서 반드시 포함할 정규화:

```text
파일명/doc_key 정규화
기관명 alias 정규화
Unicode/HWP artifact 정리
공백/줄바꿈 정규화
섹션명 정규화
날짜 형식 정규화
사업금액 표기 정규화
사업기간 표기 정규화
제출 일자/방법/장소 정규화
제출서류 중복 정리
입찰참가자격 중복 정리
사업 유형 태깅
```

특히 `사 업 비`, `사 업 금 액`, `사 업 기 간`처럼 음절 사이에 공백이 들어간 표현을 고려한다.

## stable ID 원칙

250/500/690 사이에서 같은 문서와 같은 chunk는 같은 ID를 가져야 한다.

```text
doc_id = normalized source_file 기반 hash
doc_key = eval 매칭용 canonical 문서명
chunk_id = doc_id + chunk_type + block_index + part_index + content_hash
source_store_id = doc_id + source_type + block_index + content_hash
```

`P001` 같은 순번형 ID는 내부 기준으로 쓰지 않는다.

## 검증 항목

각 산출물마다 아래 값을 저장한다.

```text
document_count
parse_success_docs
parse_failed_docs
hwpx_docs
pdf_docs
hwp_fallback_docs
chunk_count
source_store_count
duplicate_doc_id_count
duplicate_chunk_id_count
duplicate_source_store_id_count
missing_source_store_ref
missing_doc_key_count
embed_enabled_count
chunk_type_counts
fact_status_counts
fact_confidence_counts
table_count
merged_cell_count
row_type_counts
avg_content_len
p50_content_len
p95_content_len
max_content_len
jsonl_file_size_mb
```

필수 통과 기준:

```text
duplicate_chunk_id_count = 0
duplicate_source_store_id_count = 0
missing_source_store_ref = 0
parse_failed_docs는 원인 로그가 있어야 함
low confidence fact가 embed_enabled=true로 들어가면 안 됨
chunks_v2_690.jsonl은 retrieval 입력으로 감당 가능한 크기여야 함
```

## 실행 순서

```text
1. HWPX/PDF/HWP 입력 목록 고정
2. 10개 샘플로 HWPX table parser 검증
3. 250개 corpus 생성
4. validation 및 table preview 확인
5. 500개 corpus 생성
6. validation 및 파일 크기 확인
7. 690개 corpus 생성
8. validation 및 source_ref 연결 검증
9. README/manifest 자동 생성
10. retrieval 담당자에게 chunks + README + metadata_light 공유
```

## 250 Mini-Pilot 결정

전체 690개로 바로 확장하기 전에 기존 P3와 동일한 250개 샘플로 P4 HWPX corpus를 먼저 만든다.

이유:

```text
P3/P4 비교 기준을 맞출 수 있음
HWPX table-aware 구조화가 실제 retrieval에 도움이 되는지 빠르게 확인 가능
표 chunk 증가가 retrieval noise로 이어지는지 먼저 확인 가능
690개 확장 전 파일 크기와 source_ref 안정성을 확인 가능
```

현재 생성된 산출물:

```text
outputs/parsing_p4_hwpx_250/
├─ chunks_v1_250.jsonl
├─ chunks_v2_250.jsonl
├─ source_store_v1_250.jsonl
├─ source_store_250.jsonl
├─ metadata_light_250.xlsx
├─ manifest.json
├─ validation_report_v1.json
├─ validation_report.json
├─ table_preview_250.csv
└─ README.md
```

P4 250 validation 요약:

```text
parse_success_docs: 250 / 250
source_format_counts: hwpx 224, pdf 25, hwp_fallback 1
duplicate_chunk_id_count: 0
duplicate_source_store_id_count: 0
missing_source_store_ref: 0

v1 chunks: 26,664
v1 chunks size: 67.18 MiB

v2 chunks: 41,653
v2 chunks size: 86.46 MiB
v2 table chunks: 30,154
source_store_250 size: 127.11 MiB
total_table_count: 25,967
merged_cell_count: 161,392
```

해석:

```text
구조화 corpus 자체는 안정적으로 생성됨.
다만 table chunk가 크게 증가했으므로 retrieval 실험에서 noise 여부를 반드시 확인해야 함.
특히 cover/table-of-contents/layout table이 검색 상위권에 과도하게 섞이면 table filtering 또는 embed_enabled 조정이 필요함.
```

## 125 `_0521` Eval-Covered Mini-Pilot 결정

현재 125 반복 실험은 과거 전체 eval 기준이 아니라, 로컬에 공유된 `data/eval/eval_batch_01~25` 500문항 기준으로 수행한다.

중요 기준:

```text
현재 eval rows: 500
현재 eval unique physical source docs: 40
P4 HWPX 125 문서 구성: 40 eval docs + 85 filler docs
출력 폴더: outputs/parsing_p4_hwpx_125_0521/
파일명: 기존 형식 유지, 0521은 폴더명에만 사용
```

과거 문서에 남아 있는 `61개 eval physical source docs`는 전체/레거시 eval 기준이다. 현재 125 `_0521` acceptance 기준으로 사용하지 않는다.

125 `_0521` 생성 시 validation 기준:

```text
document_count == 125
eval_physical_source_docs_included == 40
additional_sampled_docs == 85
missing_eval_gt_docs == []
duplicate_chunk_id_count == 0
duplicate_source_store_id_count == 0
missing_source_store_ref == 0
```

이번 `_0521`에서 추가 반영할 수정:

```text
기초금액/예정가격/추정가격 단독 문맥은 final_budget에서 제외하고 notice_base_amount로 분리
1원/0원/소액 금액은 실제 사업예산으로 승격하지 않음
budget_value_role로 actual_project_budget / notice_base_amount / symbolic_notice_base_amount / missing_budget 구분
재공고/원공고는 병합하지 않고 project_family_key와 notice_prefix_flags로 관계만 표시
document_summary에 source_file, alias, 접두어 제거 사업명, 발주기관, 사업유형, 예산 상태, 마감/제출/자격 신호 포함
목차/표지/layout table은 embed_enabled=false로 낮춤
manifest와 validation_report에는 chunks/source_store hash와 line count를 기록
```

`json_key_description.md`는 새 폴더에 함께 생성한다. 이 문서는 `chunks_v2_125.jsonl`, `source_store_125.jsonl`, `metadata_light_125.xlsx`, `manifest.json`, `validation_report.json`의 key와 Chroma 적재 매핑을 설명한다.

## 리스크와 대응

| 리스크 | 대응 |
|---|---|
| HWPX 표가 너무 많아 파일 크기 증가 | chunks에는 compact `content/body_text`만 저장하고 full table은 source_store로 분리 |
| 병합 셀 때문에 행/열 의미 손실 | `rowspan/colspan`, `row_group`, `columns_candidate` 보존 |
| 표처럼 보이지만 배치용인 layout table 포함 | `layout_noise` 후보로 분리하고 embed 여부 제한 |
| fact_candidates가 오답을 강화 | confidence/status를 두고 낮은 신뢰도는 embed 제외 |
| 250/500/690에서 ID 불안정 | hash 기반 stable ID 사용 |
| source_store와 chunk 연결 끊김 | `missing_source_store_ref=0` 검증 필수 |
| 이미지 속 중요한 정보 누락 | P4에서는 보류하되 image count와 위치만 로그로 남김 |

## 이번 단계의 비목표

```text
Chroma 적재 최적화
임베딩 모델 비교
reranker 튜닝
generation/LCEL 연결
image OCR 전체 적용
API 기반 답변 생성
```

P4는 retrieval-ready corpus를 안정적으로 만드는 단계다.

## External G2B Metadata Policy

팀원이 공유한 G2B/나라장터 보강 데이터는 원문 RFP에서 직접 추출한 값이 아니므로 authoritative fact로 바로 사용하지 않는다.
P4 690 확장 시에는 아래 원칙으로만 반영한다.

### 반영 대상

```text
입찰마감일시
공고번호
공고차수
```

- `입찰마감일시`는 팀원 확인상 비교적 정확한 값으로 보고, P4 690 확장 시 external candidate metadata로 반영한다.
- `공고번호`는 하이픈 뒤 suffix를 공고 차수로 분리한다.
  - 예: `20240518650-001`
  - `notice_no_base = 20240518650`
  - `notice_revision_no = 001`
- 원문에서 추출한 값과 충돌할 수 있으므로, 처음부터 final field로 덮어쓰지 않는다.

권장 metadata key:

```text
external_source = g2b_team_csv
external_notice_no
external_notice_no_base
external_notice_revision_no
external_bid_deadline
external_match_status
external_match_confidence
```

### 반영 제외 대상

```text
게시일자
나라장터_공고일
```

- 게시일자/공고일은 신뢰하지 않는다.
- Chroma `documents`에 넣지 않는다.
- `fact_candidates`에 넣지 않는다.
- 최종 답변 생성 근거로 사용하지 않는다.
- 필요하면 audit용 원본 컬럼으로만 보관하고 기본 공유/검색 payload에서는 제외한다.

### 매칭 원칙

외부 G2B 정보는 아래 조건을 만족할 때만 `external_match_status=confirmed`로 둔다.

```text
normalized project name match
issuer match or high-confidence alias match
year/date consistency
not canceled notice
bid deadline exists
```

불확실하면 `needs_review` 또는 `low_confidence`로 두고 embedding 대상 content에는 넣지 않는다.

## ID And Traceability Guardrails

팀원 파일처럼 `FileName + ChunkID`만으로 원문을 추적하는 방식은 약한 역추적이다.
P4에서는 Chroma 검색 결과가 원문 근거까지 안정적으로 이어지도록 아래 검증을 필수로 둔다.

### 금지할 실수

```text
ChunkID를 그대로 Chroma ids로 사용
확장자를 제외한 파일명 기반 ID만 사용
HWP/PDF 중복 문서의 chunk id 충돌 방치
source_store_id 없이 content만 저장
row_index만으로 원문 위치를 추정
게시일자 같은 불확실한 외부 metadata를 final fact로 저장
```

### 필수 검증

```text
duplicate_doc_id_count = 0
duplicate_chunk_id_count = 0
duplicate_source_store_id_count = 0
missing_source_store_ref = 0
chroma_id_unique = true
retrieved_chunk_to_source_ref_join_success = true
external_metadata_confirmed_count / needs_review_count 기록
```

### stable id 원칙

```text
doc_id = normalized source file + extension 기반 hash
chunk_id = doc_id + chunk_type + block_index + part_index + content_hash
source_store_id = doc_id + source_type + block_index + content_hash
```

즉, 사람이 보기 쉬운 `ChunkID`는 보조 정보로만 두고 Chroma `ids`에는 안정적인 hash 기반 ID를 사용한다.
