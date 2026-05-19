# RFP RAG Baseline

공공기관 및 기업의 RFP 문서를 기반으로 질문에 답하는 RAG 시스템입니다.

현재 목표는 **이미 청킹된 데이터로 검색 결과와 답변을 눈으로 확인하는 베이스라인**을 안정화하는 것입니다. 평가 자동화와 원본 문서 parsing/chunking은 아직 다루지 않습니다.

## Current Scope

지금 되는 것:

- `data/processed/chunks_v2.jsonl` 로드
- OpenAI/HuggingFace embedding + FAISS 기반 dense retrieval
- BM25 기반 sparse retrieval
- BM25 + Dense hybrid retrieval
- Multi-query retrieval
- Local keyword reranking
- Contextual compression
- issuer/project/source/doc/chunk metadata filter
- FAISS 기본 사용, Chroma backend 비교 준비
- 검색 결과와 metadata를 터미널에 자세히 출력
- 검색 결과와 답변을 JSON으로 저장
- 검색된 chunk 본문과 metadata를 기반으로 OpenAI generator가 답변 생성

지금 하지 않는 것:

- 원본 문서 parsing
- chunking
- retrieval/generation 정량 평가
- ChromaDB 비교

## Data Flow

```text
사용자 질문
  -> RAGPipeline
  -> Retriever 선택
      -> bm25: chunks_v2.jsonl에서 키워드 기반 검색
      -> dense: 선택한 embedding preset + vector index에서 의미 기반 검색
      -> hybrid: BM25와 Dense 결과를 reciprocal-rank fusion으로 결합
  -> optional multi-query fusion
  -> optional reranking
  -> optional contextual compression
  -> metadata filter 적용
  -> 관련 chunk top-k 반환
  -> chunk 본문 + metadata를 context로 구성
  -> OpenAI Generator가 답변 생성
  -> 답변 + 출처 출력 또는 JSON 저장
```

## Project Structure

```text
chatbot/
├── data/
│   ├── raw/                 # 원본 RFP 문서. 현재 baseline에서는 직접 사용하지 않음
│   ├── processed/           # 청킹 완료된 데이터
│   │   └── chunks_v2.jsonl  # 현재 RAG가 실제로 읽는 핵심 파일
│   └── eval/                # 평가셋 보관 위치. 현재 baseline 실행에서는 사용하지 않음
│
├── indexes/                 # FAISS index 저장 위치. Git에는 올리지 않음
├── eval/                    # 평가 모듈. predictions JSONL을 받아 retrieval/RAGAS 평가
├── notebooks/               # 분석/디버깅용 노트북
├── outputs/                 # 저장된 실행 결과 위치. Git에는 올리지 않음
│
├── scripts/
│   ├── build_faiss_index.py # dense/hybrid retrieval용 FAISS index 생성
│   └── run_baseline.py      # RAG 결과를 눈으로 확인하는 메인 실행 스크립트
│
└── src/
    ├── data/                # chunk 데이터 로더
    ├── embeddings/          # OpenAI/HuggingFace embedding wrappers and presets
    ├── generator/           # OpenAI 답변 생성기
    ├── pipeline/            # 전체 RAG 흐름
    ├── retriever/           # BM25 / Dense / Hybrid 검색기
    └── vectorstore/         # FAISS/Chroma vector store
```

## Core Modules

### `src/data/loader.py`

`data/processed/chunks_v2.jsonl`을 읽어서 내부 표준 형태로 바꿉니다. 입력 데이터의 `content`는 `text`가 되고, `project_name`, `issuer`, `metadata_budget`, `amounts` 같은 값은 `metadata`에 들어갑니다.

### `src/retriever/bm25.py`

BM25 기반 sparse retriever입니다. index 생성 없이 빠르게 검색할 수 있지만, 단어 겹침에 많이 의존합니다.

### `src/retriever/dense.py`

선택한 embedding 모델과 vector store를 사용한 dense retriever입니다. 질문과 문서 chunk를 벡터 공간에서 비교합니다.

### `src/retriever/hybrid.py`

BM25 결과와 Dense 결과를 함께 가져온 뒤 reciprocal-rank fusion으로 결합합니다. 두 검색기의 장점을 섞어보는 실험용 baseline입니다.

### `src/retriever/metadata_filter.py`

검색 결과를 `issuer`, `project_name`, `source_file`, `doc_id`, `chunk_id` 기준으로 필터링합니다.

### `src/generator/openai_generator.py`

검색된 chunk context를 OpenAI 모델에 전달합니다. context에는 본문뿐 아니라 문서 metadata도 포함됩니다.

### `src/pipeline/rag_pipeline.py`

검색기 선택, metadata filter, context 구성, 답변 생성을 묶는 전체 RAG 진입점입니다.

## Run

먼저 의존성을 설치합니다. 이제 requirements 파일은 하나만 사용합니다.

```bash
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
```

그 다음 `.env`에 OpenAI API key가 있어야 합니다.

```text
OPENAI_API_KEY=...
```

### 기본 실행: Dense retrieval + OpenAI 답변 생성

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?"
```

기본값:

```text
retriever = dense
embedding_preset = openai-small
embedding_model = OpenAI text-embedding-3-small
vector DB = FAISS
answer generator = OpenAI gpt-5-mini
top_k = 5
```

기본 OpenAI-small FAISS index는 `indexes/faiss_openai/`를 사용합니다. 다른 embedding preset은 모델별로 별도 index 경로를 씁니다. 이미 index가 있으면 다시 만들지 않고 로드합니다.

### Embedding preset 선택

지원하는 preset:

```text
openai-small -> text-embedding-3-small
openai-large -> text-embedding-3-large
bge-m3       -> BAAI/bge-m3
koe5         -> nlpai-lab/KoE5
kure         -> nlpai-lab/KURE-v1
```

HuggingFace 계열 `bge-m3`, `koe5`, `kure`는 로컬 모델이라 첫 index 생성 때 모델 파일을 다운로드합니다. 지금 VM처럼 디스크가 부족하면 실제 빌드는 디스크 여유를 확보한 뒤 하는 게 좋습니다.

모델별 index 생성 예시:

```bash
.venv/bin/python scripts/build_vector_index.py --embedding-preset bge-m3
.venv/bin/python scripts/build_vector_index.py --embedding-preset koe5
.venv/bin/python scripts/build_vector_index.py --embedding-preset kure
```

검색 실행 예시:

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --embedding-preset bge-m3 \
  --no-answer
```

### 검색 결과만 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --no-answer
```

### BM25로 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --retriever bm25 --no-answer
```

### Hybrid로 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --retriever hybrid --no-answer
```

Hybrid 가중치는 조정할 수 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?"   --retriever hybrid   --hybrid-bm25-weight 0.4   --hybrid-dense-weight 0.6
```


### Multi-query / rerank / contextual compression

Multi-query는 LLM으로 질문 변형을 만들어 여러 검색 결과를 합칩니다. OpenAI API 호출이 추가로 발생합니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --multi-query \
  --multi-query-count 3 \
  --no-answer
```

Rerank는 검색 후보를 local keyword reranker로 재정렬합니다. 추가 API 호출은 없습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --rerank \
  --rerank-candidates 30 \
  --no-answer
```

Contextual compression은 검색된 chunk 본문에서 질문과 관련 있는 구간만 남겨 generation context를 줄입니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --compress-context \
  --compression-max-chars 1200
```

세 옵션은 함께 사용할 수 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --retriever hybrid \
  --multi-query \
  --rerank \
  --compress-context
```

### Vector DB backend 비교

기본 backend는 FAISS입니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --vector-store faiss
```

Chroma는 `requirements.txt`에 포함되어 있습니다. Chroma는 기본적으로 `indexes/chroma_openai/`에 저장됩니다. 디스크 여유가 생긴 뒤 index를 만들면 됩니다.

Chroma index 생성 예시:

```bash
.venv/bin/python scripts/build_vector_index.py \
  --vector-store chroma
```

Chroma 검색 예시:

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" \
  --vector-store chroma \
  --no-answer
```

원하는 저장 위치를 직접 지정할 수도 있습니다.

```bash
.venv/bin/python scripts/build_vector_index.py \
  --vector-store chroma \
  --index-dir indexes/chroma_openai
```

### Metadata filter 사용

발주기관 기준으로 검색 결과를 좁힐 수 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?"   --retriever bm25   --issuer 한국가스공사   --no-answer
```

사용 가능한 filter 옵션:

```text
--issuer
--project
--source-file
--doc-id
--chunk-id
```

### 결과 저장

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --save
```

기본 저장 위치:

```text
outputs/runs/YYYYMMDD_HHMMSS_<retriever>.json
```

원하는 경로를 직접 지정할 수도 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?"   --retriever bm25   --no-answer   --output outputs/runs/bm25_budget_check.json
```

### FAISS index 재생성

```bash
.venv/bin/python scripts/build_vector_index.py --vector-store faiss
```

기존 전용 스크립트도 유지됩니다.

```bash
.venv/bin/python scripts/build_faiss_index.py
```

또는 baseline 실행 중 강제로 다시 만들 수 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --build-index
```

## Eval 연결

현재 `eval/evaluation/`은 RAG를 직접 실행하지 않고, 이미 생성된 predictions JSONL을 받아 평가합니다. 그래서 연결 흐름은 두 단계입니다.

```text
우리 RAG 실행
  -> outputs/predictions/*.jsonl 생성
  -> eval/scripts/run_evaluation.py가 JSONL을 읽고 평가
```

### 1. predictions JSONL 생성

Phase 1 retrieval 평가만 보려면 답변 생성을 끄고 검색 결과만 저장하면 됩니다. `--generate-answer`를 주지 않는 것이 기본값입니다.

```bash
.venv/bin/python scripts/generate_eval_predictions.py \
  --retriever bm25 \
  --canonical-only \
  --limit 5
```

Dense/Hybrid 평가에서는 미리 해당 embedding index가 있어야 합니다.

```bash
.venv/bin/python scripts/generate_eval_predictions.py \
  --retriever dense \
  --embedding-preset openai-small \
  --canonical-only
```

생성되는 JSONL은 eval 모듈이 요구하는 형식에 맞춰 다음 필드를 포함합니다.

```text
id
question
answer
retrieved_contexts
latency_ms
model_name
embedding_model
retriever_config
metadata_filter
```

`retrieved_contexts` 안에는 `rank`, `filename`, `doc_id`, `chunk_id`, `score`, `text`, `metadata`가 들어갑니다. 여기서 `filename`은 chunk metadata의 `source_file`을 사용합니다. eval의 retrieval metric은 이 값을 `ground_truth_docs`와 비교합니다.

답변 생성까지 포함해 RAGAS 평가용 predictions를 만들려면 `--generate-answer`를 붙입니다. OpenAI API 호출이 문항 수만큼 발생하므로 비용에 주의합니다.

```bash
.venv/bin/python scripts/generate_eval_predictions.py \
  --retriever hybrid \
  --embedding-preset openai-small \
  --rerank \
  --generate-answer \
  --canonical-only
```

### 2. eval 실행

생성된 predictions 경로를 넘겨 Phase 1 평가를 실행합니다.

```bash
.venv/bin/python eval/scripts/run_evaluation.py \
  --predictions outputs/predictions/<파일명>.jsonl \
  --canonical-only
```

RAGAS까지 실행하려면 다음처럼 사용합니다.

```bash
.venv/bin/python eval/scripts/run_evaluation.py \
  --predictions outputs/predictions/<파일명>.jsonl \
  --canonical-only \
  --enable-ragas
```

평가 결과는 기본적으로 `eval/evaluation/outputs/eval/` 아래에 저장됩니다.

### eval 폴더 위치 판단

현재 구조는 `eval/evaluation/`처럼 한 번 더 중첩되어 있습니다. 동작은 가능하게 보정했지만, 장기적으로는 약간 헷갈릴 수 있습니다. 둘 중 하나로 정리하는 편이 더 좋습니다.

```text
추천 1: evaluation/        # 평가 코드가 프로젝트 루트에 바로 위치
추천 2: eval/              # eval 폴더 자체를 평가 코드 루트로 사용
현재:   eval/evaluation/   # 동작은 하지만 중첩이 있어 경로 설명이 복잡함
```

지금은 팀원이 가져온 평가 모듈 구조를 최대한 유지하기 위해 폴더 이동은 하지 않았습니다. 대신 `eval/scripts/run_evaluation.py`를 편의 진입점으로 두고, 내부 경로 계산이 현재 위치에서도 맞도록 보정했습니다.

## Current Baseline Goal

지금은 자동 평가보다 눈으로 확인하는 단계입니다.

우선은 같은 질문에 대해 다음을 비교합니다.

- Dense가 어떤 chunk를 가져오는지
- BM25가 어떤 chunk를 가져오는지
- Hybrid가 두 검색 결과를 잘 섞는지
- metadata filter를 걸었을 때 결과가 좁혀지는지
- 답변이 검색된 context와 metadata 안에서만 나오는지
- 출처의 `source_file`, `project`, `issuer`, `budget`, `doc_id`, `chunk_id`가 납득되는지

이 baseline이 안정되면 `scripts/generate_eval_predictions.py`로 predictions JSONL을 만들고 eval 모듈에서 정량 평가를 돌립니다.
