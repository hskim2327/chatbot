# Codeit 중급 프로젝트 - RFP Parsing 파트

```text
parsing/corpus 생성   src/parsing/, notebooks/parsing/, scripts/corpus/20260528/, scripts/corpus/20260601/, scripts/g2b/
retrieval/generation  notebooks/rag/, src/generation/, docs/plans/, docs/notes/
```

## 담당 범위 및 목표

복잡한 기업 및 정부 제안요청서(RFP)에서 검색과 답변 생성에 필요한 정보를 안정적으로 추출하고, RAG 시스템 성능 향상에 사용할 수 있는 구조화 corpus를 만드는 것이 목표입니다.
이 작업의 중심은 모델 자체보다 **RFP 데이터 구조화와 generation context 구성**입니다.

- HWP/HWPX 기반 RFP 문서 파싱
- Chroma 적재용 `chunks_v2_690.jsonl` corpus 설계
- `content + metadata + chunk_id` 기반 Chroma index payload 정리
- 사업예산, 입찰마감, 제출서류, 입찰참가자격 등 RFP 도메인 key 설계
- generation 단계에서 질문 유형에 맞게 근거를 재구성하는 context builder 설계


## 전체 흐름

```text
원본 RFP 문서
-> HWPX 변환 및 파싱
-> text / table / fact_candidates chunk 생성
-> Chroma 적재용 JSONL corpus 생성
-> Chroma 검색 + hybrid/rerank retrieval
-> 질문 유형별 context builder
-> LLM 답변 생성
```


## 설계 의도

RFP 문서에는 숫자와 날짜가 많기 때문에 단순 텍스트 검색만으로는 잘못된 근거가 답변에 쓰일 수 있습니다. 예를 들어 같은 금액이라도 실제 사업예산, 입찰 기준 금액, 지급조건 금액은 답변에서 역할이 다릅니다.

그래서 금액은 단순 숫자가 아니라 아래처럼 역할을 나눠 관리합니다.

```text
project_budget       : 실제 사업예산으로 우선 사용
total_allocation     : 전체 배정액 또는 총액 성격
estimated_price      : 추정가격
base_amount          : 기초금액 또는 예정가격 관련 값
threshold_budget     : 입찰참가자격/실적/평가 기준 금액
reference_amount     : 참고 금액 또는 예시 금액
payment_terms        : 선금/중도금/잔금 등 지급조건 금액
```

예산 답변에는 `answer_policy=allow_as_project_budget`, `budget_answer_enabled=True`인 근거를 우선 사용하도록 설계했습니다.


## 주요 JSONL 구조

`chunks_v2_690.jsonl`은 한 줄에 하나의 검색 chunk가 저장되는 JSONL 파일입니다. Chroma에 넣을 때는 아래처럼 대응됩니다.

```text
chunk_id  -> Chroma ids
content   -> Chroma documents
metadata  -> Chroma metadatas
```

```text
JSONL record
├─ chunk_id
│  └─ 청크 고유 ID. Chroma ids로 사용
│
├─ chunk_type
│  ├─ text            : 일반 문단/조항 기반 검색 청크
│  ├─ table           : 표에서 추출한 검색 청크
│  └─ fact_candidates : 예산, 기간, 제출서류, 자격요건 같은 핵심 후보 정보
│
├─ content
│  └─ 실제 임베딩 대상 텍스트. Chroma documents로 사용
│
├─ source_file
│  └─ 원본 RFP 파일명. 검색 결과 출처 표시와 정성 검토에 사용
│
├─ metadata
│  ├─ 문서 식별
│  │  ├─ issuer              : 발주기관 또는 수요기관
│  │  ├─ project_name        : 사업명
│  │  └─ document_identity   : 문서/사업 식별용 alias
│  │
│  ├─ 위치·구조
│  │  ├─ section_path        : 문서 내 장/절/항 위치
│  │  ├─ table_role          : 예산표, 평가표, 제출서류표 등 표의 역할
│  │  └─ row_group           : 병합 셀이나 묶음 행의 의미 단위
│  │
│  ├─ 답변 정책
│  │  ├─ fact_type           : 이 chunk가 담고 있는 사실 유형
│  │  ├─ answer_policy       : 최종 답변에 직접 써도 되는지에 대한 정책
│  │  ├─ confidence          : 추출 신뢰도
│  │  └─ status              : extracted, source_verified, needs_review 등
│  │
│  ├─ 금액 역할
│  │  ├─ project_budget      : 실제 사업예산, 사업비, 사업금액
│  │  ├─ total_allocation    : 전체 배정액 또는 총액 성격의 금액
│  │  ├─ estimated_price     : 추정가격
│  │  ├─ base_amount         : 기초금액 또는 예정가격 관련 값
│  │  ├─ threshold_budget    : 입찰참가자격, 실적, 평가 기준 금액
│  │  ├─ reference_amount    : 참고 금액, 예시 금액
│  │  └─ payment_terms       : 선금, 중도금, 잔금 등 지급조건 금액
│  │
│  ├─ 일정·제출
│  │  ├─ bid_deadline        : 입찰마감일시
│  │  ├─ project_duration    : 사업기간 또는 수행기간
│  │  ├─ submission_documents: 제출서류
│  │  ├─ submission_date     : 제안서 제출일자
│  │  ├─ submission_method   : 제출방법
│  │  └─ submission_place    : 제출장소
│  │
│  └─ 자격·요구사항
│     ├─ eligibility         : 입찰참가자격, 면허, 실적 조건
│     ├─ requirements        : 기능/시스템 요구사항
│     └─ technical_scope     : 기술 범위와 시스템 구성 범위
│
└─ source_ref
   └─ 필요한 경우 상세 근거를 추가 확인하기 위한 참조 key
```

## Chroma 적재 방식

```python
collection.add(
    ids=[record["chunk_id"]],
    documents=[record["content"]],
    metadatas=[record["metadata"]],
)
```

metadata에는 긴 원문이나 큰 표 전체를 넣지 않고, 검색 결과를 해석하고 필터링하는 데 필요한 짧은 값만 넣습니다.


## 최종 Slim Corpus 기준

아래 값은 최종 로컬 산출물의 slim `chunks_v2_*.jsonl` raw 파일 크기 기준입니다. 

| corpus | slim chunks 파일 | chunks 수 | raw JSONL 크기 |
|---|---|---:|---:|
| 125 | `chunks_v2_125.jsonl` | 19,853 | 63.42 MiB |
| 250 | `chunks_v2_250.jsonl` | 36,945 | 125.53 MiB |
| 690 | `chunks_v2_690.jsonl` | 106,777 | 366.61 MiB |

실험용 embedding에는 slim corpus의 `chunks_v2_*.jsonl`만 Chroma에 넣으면 됩니다. `source_store_v2_*.jsonl`은 임베딩 대상이 아니라 generation 단계에서 원문 확장과 근거 확인에 사용하는 파일입니다.


## Context Builder

generation 단계에서는 retrieval 결과를 그대로 LLM에 넣지 않고, 질문 유형에 맞게 context를 다시 조립합니다.

```text
question
-> target_slots 추출
-> intent_plan 생성
-> fact_candidates / table / text chunk 재정렬
-> computed_values 생성
-> evidence_blocks 구성
-> LLM prompt 입력
-> deterministic 후처리
```

특히 예산, 차액, 합산, 제출서류, 입찰참가자격, multi-doc 비교 질문에서 metadata를 적극적으로 사용합니다.


## Retrieval/Generaion 실험 기준

데이터 검증을 위한 retrieval 125 corpus exp100 기준 주요 결과는 다음과 같습니다.

| 조건 | 설명 | hit@5 | doc recall@5 | multi-doc recall@5 |
|---|---|---:|---:|---:|
| J0 dense | KoE5 dense baseline | 0.97 | 0.8958 | 0.7662 |
| J2 BM25 | BM25 keyword only | 0.92 | 0.8367 | 0.7130 |
| J3 RRF | dense + BM25 RRF | 0.99 | 0.9483 | 0.8843 |
| J5 hybrid | dense + BM25 RRF + reranker | 0.99 | 0.9725 | 0.9514 |

J5가 가장 안정적이지만 가장 느립니다. J3는 속도와 성능의 균형이 좋고, BM25는 단독 성능은 낮지만 숫자, 기관명, 공고명처럼 표면 단어가 중요한 질문에서 보완 역할을 합니다.

Generation은 Gemini-3.1 flash lite 모델 50문항 실험에서 JSON 형식과 숫자 grounding 안정성이 가장 좋았습니다.

```text
valid JSON 1.00 / numeric grounded 1.00 / source numeric grounded 1.00
```


## 주요 파일 위치

```text
data/690_new/README.md
data/690_new/json_key_description.md
docs/p4_data_generation_final_report_20260601.md
docs/jsonl_key_tree_three_slides.html
src/generation/rfp_generation.py
src/parsing/rfp_p4_goalfix_postprocess.py
notebooks/rag/rfp_retrieval_generation_p4_hwpx_125_pipeline_gemini.ipynb
```

## 실행 시 주의

- Chroma에는 기본적으로 `chunks_v2_*.jsonl`을 적재합니다.
- `source_store_v2_*.jsonl`은 직접 임베딩하지 않습니다.
- Chroma DB와 embedding cache는 GitHub에 올리지 않습니다.
- Google Drive에 Chroma DB를 직접 만들면 느려질 수 있으므로 Colab/GCP 로컬 런타임 경로를 권장합니다.
- corpus hash가 같다면 embedding/Chroma를 매번 새로 만들 필요가 없습니다.


## GitHub에 포함하지 않는 것

```text
data/original_data_list/
data/hwpx_664/
outputs/
Chroma DB
embedding cache
prediction JSONL
.env / API key
zip 파일
대용량 chunks/source_store JSONL
개인 회의용 HTML/대본
```

