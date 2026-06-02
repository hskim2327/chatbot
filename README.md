# KURE RAG 스크립트

이 브랜치에는 `new125` 데이터와 KURE 임베딩을 활용한 RAG 파이프라인 스크립트 2개가 포함되어 있습니다. 
## 파일 구성

- `new125+kure+langchain.py`
  - Chroma DB, dense retrieval, sparse BM25 retrieval, alias n-gram rescue, metadata reranking을 활용한 adaptive retrieval 파이프라인입니다.
  - eval CSV를 불러와 hit rate, MRR, NDCG, recall 등의 retrieval 지표를 계산합니다.
  - `sh2orc/Llama-3.1-Korean-8B-Instruct` 모델을 사용해 검색된 context 기반 답변을 생성합니다.

- `new125+kure+langgraph.py`
  - 위 adaptive retrieval 구조를 LangGraph 기반 workflow로 확장한 버전입니다.
  - 예산 관련 질문에서 로컬 context가 부족할 경우 G2B 조회 노드를 통해 보조 정보를 가져오도록 구성되어 있습니다.
  - `data.go.kr` 공공데이터 API service key가 요구됩니다. (G2B_SERVICE_KEY= 이곳에 기입)

## 주요 처리 흐름

1. Chroma vector DB를 복원하거나 로드합니다.
2. chunk metadata를 불러오고 문서 필드를 정규화합니다.
3. KURE query embedding을 생성해 dense retrieval을 수행합니다.
4. BM25 기반 sparse retrieval과 alias n-gram 검색을 수행합니다.
5. 검색 후보를 adaptive retrieval 로직으로 병합하고 재정렬합니다.
6. LLM 입력용 context를 선택합니다.
7. 한국어 instruction-tuned LLM으로 답변을 생성합니다.
8. retrieval 및 답변 생성 결과를 평가합니다.

## 설치

필요한 패키지는 `requirements.txt` 기준으로 설치합니다.

```bash
pip install -r requirements.txt
```

주요 사용 패키지는 다음과 같습니다.

- `chromadb`
- `sentence-transformers`
- `rank-bm25`
- `transformers`
- `torch`
- `pandas`
- `numpy`
- `tqdm`
- `langgraph`: LangGraph 버전에서 사용


```

## 실행 방법

DB와 환경 변수를 준비한 뒤 repository root에서 실행합니다.

```bash
python "new125+kure+langchain.py"
python "new125+kure+langgraph.py"
```
참조>
Colab Notebook에서 변환된 스크립트이므로 실행 전 파일 경로 설정이 필요합니다.
