# Legacy Plan Status

## 목적

기존에 작성된 계획 문서들을 삭제하거나 덮어쓰지 않고, 현재 기준에서 어떤 문서가 어떤 의미를 갖는지 정리한다.

터미널에서 일부 기존 Markdown 파일이 인코딩 깨짐처럼 보일 수 있으므로, 기존 파일은 보존하고 새 계획은 별도 파일로 작성한다.

## 기존 문서

| file | 현재 역할 | 상태 |
|---|---|---|
| `plan.md` | 초기 RAG 전체 설계와 팀 운영 계획 | 참고용 |
| `context_engineering_plan.md` | 초기 전처리/태깅/실험 방향 | 참고용 |
| `hwp_to_hwpx_conversion_guide.md` | HWP를 HWPX로 변환하는 절차 | 유효 |

## 진행 흐름 정리

```text
P1 초기 산출물
└─ clean text 기반 v1/v2 JSONL 생성

P1 구조화 로직 개선
└─ chunk_id 중복 수정, toc 분리, artifact cleaner 보강, fact 후보 개선

P1 Retrieval Pilot 검증
└─ 250개 corpus 기준 R0~R6 retrieval 실험으로 구조화 효과 확인

P3 Retrieval-Ready Corpus
└─ 250/500/690 전체로 확장 가능한 compact JSONL 설계
   source_store 분리, stable ID, 파일 크기 절감 적용

P4 HWPX Retrieval-Ready Corpus
└─ HWPX 기반 table-aware parsing으로 전체 690개 corpus 고도화 예정
```

## 현재 기준 문서

지금부터 실행 기준은 아래 문서다.

```text
docs/plans/p4_hwpx_retrieval_ready_plan.md
```

P4에서는 기존 P3의 compact retrieval-ready 원칙을 유지하되, HWPX XML에서 표 구조를 직접 읽어 table 품질을 높인다.

## 보존 원칙

- 기존 문서는 과거 의사결정 기록으로 남긴다.
- 새 corpus 설계는 P4 문서를 기준으로 한다.
- GitHub 공유 시에는 최신 계획 문서와 산출물 README를 우선 안내한다.
- 원본 RFP, source_store, Chroma DB, embedding cache는 기본 공유 대상에서 제외한다.
