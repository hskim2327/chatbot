# DB RAG Codeit Project

공공/기업 RFP 문서를 구조화하고, Chroma 기반 retrieval 실험까지 재현하기 위한 프로젝트입니다.

## Repository Scope

GitHub에는 코드, 노트북, 설명 문서만 포함합니다. 아래 파일은 용량과 재현 환경 차이 때문에 업로드하지 않습니다.

- 원본 RFP 데이터: `data/original_data_list/`
- PDF 변환본 및 압축 파일: `data/pdf_186/`, `*.zip`
- 파싱/청킹 산출물: `outputs/`
- Chroma DB, embedding cache, prediction JSONL
- `.env`, API key, 로컬 가상환경

필요한 데이터와 산출물은 공유 Drive 또는 로컬 PC에 별도로 배치한 뒤 노트북 상단 경로만 맞춰 실행합니다.

## Main Folders

```text
project_2nd/
├─ notebooks/
│  ├─ parsing/             # HWP/PDF 추출, artifact 정제, P1/P2 JSONL corpus 생성
│  ├─ rag/                 # KoE5 embedding, Chroma/BM25/RRF/reranker retrieval 실험
│  ├─ eval/                # retrieval/generation 평가 모듈
│  ├─ context_engineering/ # 초기 context engineering 및 sanity check
│  └─ env/                 # GCP/Colab 환경 설정 참고
├─ src/parsing/            # 파싱 공통 라이브러리
├─ docs/                   # 프로젝트 계획 및 협업 메모
├─ data/                   # 로컬 데이터 위치, 원본은 GitHub 제외
└─ outputs/                # 로컬 산출물 위치, GitHub 제외
```

## Recommended Order

1. `notebooks/parsing/hwp_text_extraction_test.ipynb`
   - HWP 원문 추출과 artifact 정제 검증
2. `notebooks/parsing/rfp_parsing_p2_250_pipeline.ipynb`
   - 250개 pilot corpus 기준 P2 JSONL 생성
3. `notebooks/parsing/quick_check_rag_chunks_p2_250.ipynb`
   - chunk 품질과 핵심 필드 sanity check
4. `notebooks/rag/embedding_retrieval_eval_v2_p2.ipynb`
   - KoE5 embedding, Chroma indexing, R0~R6 retrieval 평가
5. `notebooks/eval/evaluation/scripts/run_retrieval_eval_extended.py`
   - retrieval 지표 확장 평가 및 누적 CSV append

## Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Colab/GCP L4에서는 CUDA용 `torch`가 이미 제공되는 경우가 많으므로 `requirements.txt`에는 `torch`를 고정하지 않았습니다.

## Corpus Naming

- `corpus_name`: `p2_250`
- `corpus_version`: `v2_p2`
- `parsing_label`: `p2_chunkfix_toc_clean`
- 기본 retrieval 파일: `outputs/parsing_p2_250/chunks_v2.jsonl`
- v1 baseline 파일: `outputs/parsing_p2_250/chunks_v1.jsonl`

산출물은 GitHub에 포함하지 않고, 필요한 경우 공유 Drive로 전달합니다.
