# TEAM 3_RFP 문서 검색 Chatbot

나라장터 RFP 문서를 발주기관 기준으로 검색하고, 선택한 문서 근거를 바탕으로 답변하는 RAG chatbot입니다.

## 프로젝트 소개

본 프로젝트는 나라장터 RFP 문서를 대상으로 발주기관 필터 기반 문서 검색과 질의응답을 수행하는 chatbot입니다.  
사용자는 발주기관을 선택한 뒤 질문을 입력할 수 있으며, 시스템은 ChromaDB에 저장된 문서 chunk를 검색하고 LLM을 통해 답변을 생성합니다.

주요 기능은 다음과 같습니다.

- 발주기관 기반 문서군 필터링
- Dense retrieval + sparse retrieval 기반 hybrid 검색
- metadata 기반 reranking
- 질문 유형별 context selection
- OpenAI 또는 HuggingFace transformers LLM 선택 실행
- 나라장터 G2B 공고번호 기반 추가 확인 안내

## 팀원 및 역할

| 역할 | 팀원 |
|---|---|
| PM | 김현숙 |
| data processing (text, chunk) | 조용준, 유소연 |
| huggingface line (embedding + llm) | 김현숙, 김범수 |
| openai line | 송우현 |
| 평가지표 | 이다현 |
| 보고서, PPT | 조용준 |

## 폴더 구성

```text
main/
  main.py
  app/
  frontend/
  .streamlit/
  ingest/
  .env
  requirements.txt
  README.md
```

`main/` 폴더를 통째로 다운로드한 뒤 실행하세요.

## 사전 준비

Python 3.11 사용을 권장합니다.

```powershell
cd main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 데이터 준비

ChromaDB 데이터는 아래 위치에 있어야 합니다.

```text
main/ingest/KuRe/
  chroma.sqlite3
  <vector index folder>/
```

기본 `.env` 설정은 다음 경로를 사용합니다.

```env
CHROMA_DB_PATH=./ingest/KuRe
COLLECTION_NAME=new_125_kurev1_v2
```

## API Key 설정

배포용 `.env`에는 key 값이 비어 있습니다. 실행 전에 본인의 key를 직접 입력해야 합니다.

### 1. OpenAI 사용

OpenAI 모델을 사용하려면 `.env`를 다음처럼 설정하세요.

```env
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=본인의_OpenAI_API_Key
```

### 2. HuggingFace Transformers 사용

로컬 HuggingFace 모델을 사용하려면 `.env`를 다음처럼 설정하세요.

```env
LLM_PROVIDER=transformers
VLLM_MODEL=sh2orc/Llama-3.1-Korean-8B-Instruct
```

이 경우 HuggingFace의 `sh2orc/Llama-3.1-Korean-8B-Instruct` 모델을 로컬에서 불러옵니다.  
모델 다운로드와 CPU 추론에는 시간이 오래 걸릴 수 있습니다.

필요한 경우 HuggingFace token을 입력하세요.

```env
HUGGINGFACE_HUB_TOKEN=본인의_HuggingFace_Token
```

### 3. 나라장터 G2B API 사용

나라장터 입찰공고정보서비스 API를 사용하려면 아래 사이트에서 API 활용 신청 후 service key를 발급받아 `.env`에 입력하세요.

[나라장터 입찰공고정보서비스 API](https://www.data.go.kr/data/15129394/openapi.do)

```env
G2B_SERVICE_KEY=본인의_나라장터_API_Key
```

## 실행 방법

터미널을 2개 열어 실행합니다.

### 터미널 1: FastAPI 서버

```powershell
cd main
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

정상 확인:

```text
http://localhost:8000/health
http://localhost:8000/issuers
```

### 터미널 2: Streamlit UI

```powershell
cd main
.\.venv\Scripts\Activate.ps1
python -m streamlit run main.py
```

접속:

```text
http://localhost:8501
```

## 사용 방법

1. 발주기관 필터에서 하나 이상의 기관을 선택합니다.
2. 질문 입력창에 질문을 작성합니다.
3. 검색 버튼을 누릅니다.
4. 답변과 참고 문서를 확인합니다.

## 주의 사항

- `.env`의 key 값은 GitHub에 실제 값으로 올리지 마세요.
- OpenAI 사용 시 `OPENAI_API_KEY`가 필요합니다.
- 나라장터 API 사용 시 `G2B_SERVICE_KEY`가 필요합니다.
- HuggingFace 모델이 비공개 또는 인증 필요 상태라면 `HUGGINGFACE_HUB_TOKEN`이 필요할 수 있습니다.
- 로컬 transformers 모드는 CPU 환경에서 느릴 수 있습니다.
