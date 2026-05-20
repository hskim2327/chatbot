# RFP RAG Plan Documents

## 현재 읽을 문서

```text
p4_hwpx_retrieval_ready_plan.md
```

현재 실행 계획은 P4 HWPX 기반 retrieval-ready corpus 생성이다.

핵심 목표:

```text
690개 RFP 전체 대상
HWPX 우선 파싱
표 구조 보존
retrieval-ready JSONL 생성
Chroma index payload와 source reference payload 분리
파일 용량 제어
stable ID 유지
```

## 문서 구조

| file | 설명 |
|---|---|
| `p4_hwpx_retrieval_ready_plan.md` | HWPX 기반 P4 corpus 전체 설계 |
| `p4_690_expansion_execution_plan.md` | P4 690 확장, G2B metadata 반영, Chroma 운영 주의사항 |
| `legacy_plan_status.md` | 기존 plan 문서들의 역할과 현재 상태 요약 |
| `hwp_to_hwpx_conversion_guide.md` | HWP를 HWPX로 변환하는 절차 |
| `plan.md` | 초기 RAG 전체 설계 기록 |
| `context_engineering_plan.md` | 초기 context engineering 실험 계획 기록 |

## 산출물 기준

P4 산출물은 아래처럼 분리한다.

```text
retrieval 입력용
├─ chunks_v1_*.jsonl
└─ chunks_v2_*.jsonl

선택적 상세 근거 조회용
└─ source_store_*.jsonl

참고용
├─ metadata_light_*.xlsx
├─ validation_report.json
├─ manifest.json
└─ README.md
```

기본 공유 대상은 `chunks`, `metadata_light`, `README`, `validation_report`다.

`source_store`, 원본 RFP, Chroma DB, embedding cache는 기본 공유 대상이 아니다.

기본 generation 입력은 Chroma 검색 결과의 `documents + metadatas`다. `source_store`는 표 원형, 긴 원문 근거, UI 원문 보기처럼 추가 조회가 필요한 경우에만 사용한다.

## External G2B Metadata And ID Guardrails

P4에서는 외부 G2B/나라장터 보강 데이터를 원문 추출값과 동일한 신뢰도로 취급하지 않는다.

- 사용 후보: `입찰마감일시`, `공고번호`, `공고차수`
- 제외: `게시일자`, `나라장터_공고일`
- `공고번호`의 하이픈 뒤 suffix는 공고 차수로 분리한다.
- 외부값은 `external_*` metadata로 넣고, 검증 전에는 final fact나 embedding content로 넣지 않는다.

또한 Chroma `ids`에는 사람이 만든 `ChunkID`를 그대로 쓰지 않는다. `chunk_id`는 hash 기반 stable id로 만들고, 검색 결과가 `source_store_id`를 통해 원문 근거와 연결되는지 검증한다.

