# RFP RAG Baseline

공공기관 및 기업의 RFP 문서를 기반으로 질문에 답하는 RAG 시스템입니다.

현재 목표는 거창한 실험 환경이 아니라, **이미 청킹된 데이터로 처음부터 끝까지 한 번 돌아가는 베이스라인**을 만드는 것입니다.

지금 단계에서는 다음을 하지 않습니다.

- 원본 문서 parsing
- chunking
- retrieval/generation 정량 평가
- hybrid retrieval
- HuggingFace 모델 비교
- ChromaDB 비교

지금 단계에서 하는 것은 다음입니다.

- `data/processed/chunks_v2.jsonl` 로드
- 기본값으로 OpenAI embedding + FAISS 기반 dense retrieval 실행
- 필요하면 BM25 기반 sparse retrieval로 전환
- 검색된 chunk를 눈으로 확인
- 검색된 chunk를 기반으로 OpenAI generator가 답변 생성

## Data Flow

```text
사용자 질문
  -> RAGPipeline
  -> Retriever 선택
      -> bm25: chunks_v2.jsonl에서 바로 검색
      -> dense: OpenAI embedding + FAISS index에서 검색
  -> 관련 chunk top-k 반환
  -> OpenAI Generator가 chunk만 보고 답변 생성
  -> 답변 + 출처 출력
```

## Project Structure

```text
chatbot/
├── data/
│   ├── raw/                 # 원본 RFP 문서. 현재 코드에서는 직접 사용하지 않음
│   ├── processed/           # 청킹 완료된 데이터
│   │   └── chunks_v2.jsonl  # 현재 RAG가 실제로 읽는 핵심 파일
│   └── eval/                # 나중에 평가할 때 사용할 데이터. 지금 baseline에서는 사용하지 않음
│
├── indexes/                 # FAISS index 저장 위치. Git에는 올리지 않음
│
├── notebooks/               # 분석/디버깅용 노트북
│
├── outputs/                 # 실행 결과, 로그, 실험 결과 저장 위치. Git에는 올리지 않음
│
├── scripts/
│   ├── build_faiss_index.py # dense retrieval용 FAISS index 생성
│   └── run_baseline.py      # BM25/Dense RAG 결과를 눈으로 확인하는 메인 실행 스크립트
│
└── src/
    ├── data/                # chunk 데이터 로더
    ├── embeddings/          # OpenAI embedding wrapper
    ├── generator/           # OpenAI 답변 생성기
    ├── pipeline/            # 전체 RAG 흐름
    ├── retriever/           # BM25 / Dense 검색기
    └── vectorstore/         # FAISS vector store
```

## Core Modules

### `src/data/loader.py`

`data/processed/chunks_v2.jsonl`을 읽어서 검색기가 쓰기 쉬운 형태로 바꿉니다.

입력 데이터의 `content` 필드는 내부에서 `text`로 바뀝니다.
`project_name`, `issuer`, `budget`, `dates` 같은 값은 `metadata` 안에 들어갑니다.

### `src/retriever/bm25.py`

BM25 기반 sparse retriever입니다.

```text
query -> query.split() -> BM25 점수 계산 -> top-k chunk 반환
```

장점은 빠르고 index 생성이 필요 없다는 점입니다.
단점은 한국어 문장 의미를 깊게 이해하지 못하고, 단어 겹침에 많이 의존한다는 점입니다.

### `src/embeddings/openai_embedder.py`

OpenAI embedding API를 감싼 모듈입니다.

- 여러 chunk를 batch로 embedding
- 질문 하나를 embedding
- 일시적인 API 실패에 대해 retry

### `src/vectorstore/faiss_store.py`

FAISS 기반 vector store입니다.

- embedding을 FAISS index로 저장
- query embedding과 가까운 chunk 검색
- index를 `indexes/faiss_openai/`에 저장하고 다시 로드

### `src/retriever/dense.py`

OpenAI embedding과 FAISS를 합쳐서 dense retrieval을 수행합니다.

BM25와 같은 형태로 사용할 수 있게 `retrieve(query, top_k)` 인터페이스를 맞췄습니다.

### `src/generator/openai_generator.py`

검색된 chunk들을 context로 묶어서 OpenAI 모델에 전달합니다.

프롬프트의 핵심 원칙은 다음입니다.

```text
아래 문맥을 기반으로만 답변해라.
문맥에 없는 내용은 추측하지 말고 모른다고 답해라.
```

### `src/pipeline/rag_pipeline.py`

전체 흐름을 묶는 진입점입니다.

```python
pipeline = RAGPipeline(retriever_type="bm25")
result = pipeline.run("질문")
```

또는 dense retrieval을 사용할 수 있습니다.

```python
pipeline = RAGPipeline(retriever_type="dense")
result = pipeline.run("질문")
```

## Run

먼저 `.env`에 OpenAI API key가 있어야 합니다.

```text
OPENAI_API_KEY=...
```

### 1. 기본 실행: Dense retrieval + OpenAI 답변 생성

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?"
```

기본값은 다음과 같습니다.

```text
retriever = dense
embedding = OpenAI text-embedding-3-small
vector DB = FAISS
answer generator = OpenAI gpt-5-mini
```

FAISS index가 없으면 첫 실행 때 `indexes/faiss_openai/`에 자동으로 생성합니다.
이미 index가 있으면 다시 만들지 않고 로드합니다.

### 2. Dense로 검색 결과만 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --no-answer
```

### 3. Dense index를 명시적으로 만들기

```bash
.venv/bin/python scripts/build_faiss_index.py
```

또는 baseline 실행 중 강제로 다시 만들 수 있습니다.

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --build-index
```

### 4. BM25로 검색 결과만 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --retriever bm25 --no-answer
```

### 5. BM25로 검색 + 답변 생성까지 보기

```bash
.venv/bin/python scripts/run_baseline.py "사업 예산 규모는 얼마입니까?" --retriever bm25
```

## Current Baseline Goal

지금은 숫자로 평가하는 단계가 아닙니다.

우선은 같은 질문에 대해 다음을 눈으로 비교합니다.

- BM25가 어떤 chunk를 가져오는지
- Dense retrieval이 어떤 chunk를 가져오는지
- 검색 결과가 질문과 관련 있어 보이는지
- 답변이 검색된 context 안에서만 나오는지
- 출처 chunk의 `project`, `issuer`, `doc_id`, `chunk_id`가 납득되는지

이 baseline이 안정되면 다음 단계에서 evaluation과 hybrid retrieval을 다시 추가합니다.
