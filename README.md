RFP RAG System

공공기관 및 기업의 RFP(Request For Proposal) 문서를 기반으로 질의응답을 수행하는 Retrieval-Augmented Generation(RAG) 시스템 프로젝트입니다.

본 프로젝트의 목표는 대량의 입찰 및 제안 요청 문서에서 사용자가 원하는 정보를 빠르고 정확하게 검색하고, 관련 내용을 기반으로 신뢰도 있는 답변을 생성하는 것입니다.

프로젝트는 단순 QA 시스템 구현에 그치지 않고, Retrieval 성능 향상과 Generation 품질 개선을 위한 다양한 실험을 수행하는 것을 핵심 목표로 합니다.

Project Goal

본 프로젝트의 최종 목표는 다음과 같습니다.

대규모 RFP 문서에 대한 효율적인 검색 시스템 구축
문서 기반 질의응답(RAG) 파이프라인 구현
Dense Retrieval / Sparse Retrieval 비교 실험
다양한 임베딩 모델 및 검색 전략 성능 비교
Hallucination 감소 및 응답 신뢰성 향상
Retrieval 및 Generation 품질 평가 자동화
실험 가능한 구조의 모듈형 RAG 시스템 설계
Current Progress

현재까지 다음 작업이 완료되었습니다.

Data Processing
RFP 문서 chunk 데이터 확보
JSONL 기반 chunk 구조 정리
metadata 기반 데이터 구조 설계

현재 chunk 데이터는 다음 정보를 포함합니다.

문서 ID
프로젝트명
발주 기관
섹션 정보
금액 및 날짜 정보
본문 텍스트
Project Structure

프로젝트는 실험 확장성과 모듈 교체 가능성을 고려하여 구조화하였습니다.

src/
├── data/
├── embeddings/
├── retriever/
├── vectorstore/
├── generator/
├── pipeline/
├── evaluation/
└── utils/
Retrieval Baseline

현재 BM25 기반 Sparse Retrieval baseline을 구축 중입니다.

목표:

naive retrieval baseline 확보
Dense Retrieval과 성능 비교 기준점 생성
Retrieval evaluation 파이프라인 구축
Generation Pipeline

OpenAI 기반 Generator 모듈을 구축 중입니다.

현재 목표:

Retrieval 결과를 기반으로 context-aware generation 수행
Hallucination 감소
출처 기반 응답 생성
Planned Architecture

최종적으로 다음 구조를 목표로 합니다.

User Query
    ↓
Query Processing
    ↓
Retriever
    ├── BM25
    ├── Dense Retrieval
    └── Hybrid Retrieval
    ↓
Reranking / Metadata Filtering
    ↓
Context Selection
    ↓
LLM Generation
    ↓
Answer + Source
Planned Experiments

본 프로젝트는 다양한 Retrieval 및 Generation 전략에 대한 비교 실험을 수행할 예정입니다.

Retrieval Experiments
Sparse Retrieval
BM25
TF-IDF
Dense Retrieval
OpenAI Embedding
HuggingFace Embedding
BGE
E5 계열 모델
Hybrid Retrieval
BM25 + Dense Retrieval 결합
Retrieval Optimization
Metadata Filtering
Top-k 비교
MMR(Maximal Marginal Relevance)
Re-ranking
Multi-query Retrieval
Vector Database

Dense Retrieval을 위해 Vector Database 구축을 진행할 예정입니다.

현재 고려 중인 기술:

FAISS
ChromaDB

비교 항목:

검색 속도
Retrieval 성능
메모리 효율성
확장성
Evaluation Strategy

본 프로젝트는 Retrieval과 Generation을 분리하여 평가합니다.

Retrieval Evaluation

예정 지표:

Recall@K
MRR
Context Precision
Generation Evaluation

예정 지표:

Faithfulness
Answer Relevancy
Context Utilization
Hallucination Rate
Long-term Objectives

최종적으로 다음과 같은 시스템을 목표로 합니다.

다양한 Retrieval 전략을 실험 가능한 구조
모듈 교체가 가능한 RAG 파이프라인
실제 문서 기반 신뢰 가능한 QA 시스템
실험 결과 기반 Retrieval 최적화
재현 가능한 Evaluation 환경 구축
Current Focus

현재 우선순위는 다음과 같습니다.

Dense Retrieval 구축
OpenAI Embedding 파이프라인 구현
FAISS 기반 Vector Store 구축
Dense Retriever 성능 검증
Retrieval Evaluation 자동화
BM25 vs Dense Retrieval 비교 실험
Notes
원본 데이터는 외부 공유를 금지합니다.
.env, vector index, processed data는 GitHub에 업로드하지 않습니다.
실험 결과 및 평가 로그는 outputs/에 저장합니다.