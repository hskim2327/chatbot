# Codeit 중급 프로젝트 - RFP Parsing 파트 유소연

## 담당 범위 및 목표

복잡한 기업 및 정부 제안요청서(RFP)에서 검색과 답변 생성에 필요한 정보를 안정적으로 추출하고, RAG 시스템 성능 향상에 사용할 수 있는 구조화 corpus를 만드는 것이 목표입니다.
이 작업의 중심은 모델 자체보다 **RFP 데이터 구조화**입니다.
검색/답변 생성은 데이터 보정이 실제 성능에 어떤 영향을 줬는지 검증하기 위한 용도로 사용합니다.

- HWP/HWPX 기반 RFP 문서 파싱
- Chroma 적재용 `chunks_v2_690.jsonl` corpus 설계
- `content + metadata + chunk_id` 기반 Chroma index payload 정리
- 사업예산, 입찰마감, 제출서류, 입찰참가자격 등 RFP 도메인 key 설계
- generation 단계에서 질문 유형에 맞게 근거를 재구성하는 context builder 설계

## Main Folders

```text
chatbot/
├─ notebooks/
│  └─ rag/                 # 검색, 답변 생성, QLoRA 실험 노트북
├─ src/
│  ├─ parsing/             # HWPX 파싱, 데이터 보정, corpus 후처리 코드
│  └─ generation/          # context builder, 답변 생성 후처리, QLoRA dataset builder
├─ eval/
│  └─ teamate/             # 팀원 평가 지표와 adapter
├─ docs/                   # 보고서, 발표 보조 자료, 실험 계획
├─ data/
│  └─ 690_new/             # 최종 공유용 slim corpus와 검수용 full corpus
└─ outputs/                # 로컬 산출물 위치, GitHub 제외
```

## 설계 의도

핵심은 단순히 문서를 청크로 나누는 것이 아니라, RFP 안의 예산, 기간, 제출서류, 자격, 공고 정보, 원문 근거를 구분해 검색과 답변 생성에서 잘못 섞이지 않게 만드는 것입니다.

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



## 주요 JSONL 구조

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

`chunks_v2_690.jsonl`은 한 줄에 하나의 검색 chunk가 저장되는 JSONL 파일입니다. Chroma에 넣을 때는 아래처럼 대응됩니다.

```python
collection.add(
    ids=[record["chunk_id"]],
    documents=[record["content"]],
    metadatas=[record["metadata"]],
)
```

metadata에는 긴 원문이나 큰 표 전체를 넣지 않고, 검색 결과를 해석하고 필터링하는 데 필요한 짧은 값만 넣습니다.


## 최종 산출물

현재 최종 공유 기준은 `./690_new`입니다. (구글 드라이브)

- 기본 검색 파일: `data/690_new/chunks_v2_690.jsonl`
- 검수용 상세 파일: `data/690_new/chunks_v2_690_full.jsonl`
- 원문 저장소: `data/690_new/source_store_v2_690.jsonl`
- 검증 파일: `data/690_new/validation_report_v2.json`
- 파일 해시/크기 기록: `data/690_new/manifest.json`

| corpus | slim chunks 파일 | chunks 수 | raw JSONL 크기 |
|---|---|---:|---:|
| 125 | `chunks_v2_125.jsonl` | 19,853 | 63.42 MiB |
| 250 | `chunks_v2_250.jsonl` | 36,945 | 125.53 MiB |
| 690 | `chunks_v2_690.jsonl` | 106,777 | 366.61 MiB |
| 690 | `chunks_v2_690_full.jsonl` | 106,777 | 476.89 MiB |

기본 검색과 Chroma 적재에는 `chunks_v2_690.jsonl`을 사용합니다. `chunks_v2_690_full.jsonl`은 전체 key와 보정 흔적 확인용이고, `source_store_v2_690.jsonl`은 검색된 청크의 긴 원문이나 표 근거를 다시 확인할 때 사용합니다.

최종 실행용 corpus는 690개 문서, 106,777개 청크 기준입니다. 검수용 상세 corpus는 상위 key 74개, metadata key 91개를 유지했고, 실행용 corpus는 상위 key 10개, metadata key 57개로 줄였습니다. 청크 수는 유지하면서 파일 크기는 500.05 MB에서 384.42 MB로 줄였습니다.



## Retrieval실험을 통한 검증

초기 v1은 정제 텍스트를 일정 길이로 나눈 기준선에 가까웠고, v2는 표 구조, 문서 요약, 예산/기간/제출서류 같은 핵심 후보, 원문 참조를 분리한 구조화 corpus입니다.

| 기준 | 설명 |  Hit@5 | MRR@5 | nDCG@5 | Doc Recall@5 | Multi-doc Recall@5 | Latency
|---|---:|---:|---:|---:|---:|---:|
| v1 초기 | KoE5 dense baseline | 0.942 | 0.867 | 0.790 | 0.806 | 0.635 | avg 28.69ms |
| v2 초기 | dense + BM25 RRF + reranker | 0.980 | 0.958 | 0.886 | 0.878 | 0.750 | avg 3263.32ms |
| v2 최고 hybrid | dense + BM25 RRF + reranker  | 0.9578 | 0.9825 | 0.9792 | P95 3602.69ms |

이 결과는 JSON key 구조화와 표 추출이 실제 검색 품질 개선에 긍정적으로 작용했다는 근거입니다. 특히 여러 문서를 함께 찾아야 하는 질문에서 개선 폭이 컸습니다.


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


## Generaion 실험

실제 답변을 생성하여 나타난 실패 사례를 기반으로 데이터롤 보완했습니다.
API 모델과 허깅페이스 모델을 함께 비교한 결과 API 모델은 품질 상한선 확인용이고, 허깅페이스 모델은 로컬/제한 환경에서 안정화가 필요했습니다.

| 모델 | 특징 | 한계 |
|---|---|---|
| Gemini 3.1 Flash Lite | JSON 안정성, 속도, 숫자 근거성이 좋음 | 호출 제한과 비용 제약이 있음 |
| Qwen2.5-3B Instruct | 허깅페이스 모델 중 가장 안정적인 기준선 | 복합 질문과 근거 선택은 보완 필요 |
| Qwen3-4B Instruct | 숫자 답변은 강해질 수 있으나 프롬프트 민감도가 큼 | 한국어 RAG 프롬프트와 후처리 조정이 더 필요 |

대표 실험 수치는 아래와 같습니다. RAGAS는 비용 문제로 일부 샘플만 평가했기에 신뢰도는 낮을 수 있습니다.

| JSON 정상률 | 빈 답변 | 숫자 근거성 | 평균 생성 시간 | Faithfulness | Context Recall | Context Precision | Answer Relevancy
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemini 3.1, 20260602_043709 | 1.00 | 0.00 | 0.96 | 약 4.9초 | 0.8381 | 0.8 | 0.6573| 0.8889 |
| Qwen2.5-3B, 20260528_014912 | 0.96 | 0.00 | 0.94 | 약 13.0초 | 0.68 | 0.6 | 0.6667 | 재평가 필요 |
| Qwen3-4B Simple, 20260602_043002 | 0.98 | 0.00 | 별도 검증값 미저장 | 약 16.5초 | 0.6 | 0.6 | 0.6293 | 0.7863


## 주요 파일 위치

데이터 담당 기준으로 확인해야 하는 주요 파일은 아래와 같습니다.

| 구분 | 파일 | 설명 |
|---|---|---|
| 최종 데이터 설명 | `data/690_new/README.md` | 최종 공유 corpus 구성, 파일 용도, 사용 기준 정리 |
| JSON key 설명 | `data/690_new/json_key_description.md` | `chunks_v2_690.jsonl`, `source_store_v2_690.jsonl`의 key 구조와 사용 기준 설명 |
| 최종 데이터 보고서 | `docs/ysy_data_generation_final_report.md` | 데이터 생성, 보정, v1/v2 검색 성과, generation 실험까지 정리한 최종 보고서 |
| 발표 보조 자료 | `docs/retrieval_v1_v2_ppt_example.html` | v1/v2 corpus 차이와 검색 성능 개선을 발표용으로 요약한 HTML |
| 데이터 보정 코드 | `src/parsing/rfp_p4_goalfix_postprocess.py` | 예산, 입찰마감일, 공고번호, source reference 등 최종 corpus 보정 로직 |


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

