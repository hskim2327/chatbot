# RFP RAG Assistant

공공기관/기업 RFP 문서를 기반으로 검색, 생성, 평가, 간단한 챗봇 서비스까지 연결한 RAG 프로젝트입니다.

이 저장소는 최종 코드와 평가 모듈을 중심으로 정리되어 있습니다. 대용량 데이터, 벡터 DB, 모델 캐시, 실행 결과는 Git에 올리지 않고 로컬에서 관리합니다.

## 현재 상태

최종 파이프라인은 다음 흐름으로 구성되어 있습니다.

```text
질문
  -> retrieval
  -> evidence/context 구성
  -> Qwen 기반 generation
  -> 후처리 및 history 처리
  -> Phase1/2/3/4 평가
  -> 웹 챗봇 서비스
```

핵심 방향은 단순히 정답 문서를 찾는 것이 아니라, **답변에 필요한 근거 evidence를 context에 넣는 것**입니다.

## 대표 문서

복잡한 실험 파일 대신 아래 문서를 먼저 보면 됩니다.

| 문서 | 설명 |
|---|---|
| [docs/final_report.md](docs/final_report.md) | 프로젝트 최종 보고서 |
| [docs/evaluation_summary.md](docs/evaluation_summary.md) | `eval` 기준 최종 평가 요약 |
| [docs/experiment_log.md](docs/experiment_log.md) | 주요 retrieval/generation 실험 기록 |
| [docs/peft_summary.md](docs/peft_summary.md) | PEFT 실험 요약 |
| [docs/service_guide.md](docs/service_guide.md) | 로컬 챗봇 서비스 실행 안내 |

기존 상세 산출물은 `outputs/` 아래에 남아 있지만, `outputs/`는 Git ignore 대상입니다.

## 최종 평가 요약

최신 공식 평가는 팀 공통 평가 모듈인 `eval` 기준으로 실행했습니다.

평가 결과 폴더:

```text
Phase1/Phase3 공식 산출물:
outputs/eval/new_eval_126_eval_schema_gold50_phase13_official/

RAGAS/Phase4 API 산출물:
outputs/eval/new_eval_126_full_ragas_phase34_openai_gold50/
```

주요 수치:

| 구분 | 지표 | 값 |
|---|---|---:|
| Phase1 Retrieval | hit@5 | 1.000 |
| Phase1 Retrieval | MRR@5 | 0.920 |
| Phase1 Retrieval | nDCG@5 | 0.911 |
| Phase2 RAGAS | faithfulness | 0.464 |
| Phase2 RAGAS | answer_relevancy | 0.141 |
| Phase3 Domain | phase3_task_score | 0.541 |
| Phase3 Domain | budget_numeric_accuracy | 0.229 |
| Phase4 LLM Judge | overall score | 69.1점 |

Phase4는 `gpt-4o-mini` API judge로 실행했으며, 50개 중 49개가 평가 완료되고 1개 validation 실패가 있었습니다.

## 주요 개선 내용

### Retrieval

- KURE embedding + Chroma 기반 검색
- query decomposition
- RRF merge
- document-level scoring
- target-aware retrieval
- evidence recall 진단
- 문서 중복 완화 및 문서별 핵심 evidence 보장

### Generation

- Qwen3 8B 4bit 기반 생성
- source_store/sidecar 기반 context 보강
- 질문 유형별 context 구성
- 예산/금액 정규화
- 제출서류/자격요건/마감일 유형별 evidence 우선순위
- 짧고 서비스 친화적인 답변 후처리
- history 기반 후속 질문 처리

### PEFT

- ChatGPT로 labeling bundle 생성
- trainable 라벨 검수
- Qwen3 8B 4bit 대상 LoRA/QLoRA 실험
- base vs adapter 비교
- 현재는 PEFT보다 retrieval/context 개선 효과가 더 컸음

## 프로젝트 구조

```text
chatbot/
├── data/                 # 로컬 데이터 위치. 실제 데이터는 Git에 올리지 않음
├── docs/                 # GitHub 공유용 정리 문서
├── eval/                 # 팀 공통 최신 평가 모듈
├── experiments/          # 실험용 실행 스크립트
├── notebooks/            # 분석용 노트북
├── scripts/              # index 생성, prediction 생성, 서비스 실행 스크립트
├── src/                  # RAG 핵심 모듈
├── indexes/              # 로컬 vector DB. Git에 올리지 않음
└── outputs/              # 실행/평가/보고서 산출물. Git에 올리지 않음
```

## 로컬 데이터

이 저장소에는 대용량 데이터가 포함되지 않습니다.

로컬 실행에는 보통 아래 파일이 필요합니다.

```text
data/processed/chunks_v2_690.jsonl
data/processed/source_store_v2_690.jsonl
indexes/chroma_kure_v1_chunks_v2_690/
```

평가나 보고서 작성에 사용한 output 파일은 `outputs/` 아래에 남아 있지만, Git에는 올라가지 않습니다.

## 설치

```bash
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
```

OpenAI API 평가를 실행하려면 `.env`에 API key가 필요합니다.

```text
OPENAI_API_KEY=...
```

`.env`는 Git ignore 대상입니다. API key는 절대 커밋하지 않습니다.

## 챗봇 서비스 실행

```bash
.venv/bin/python scripts/rag_service_web.py \
  --host 127.0.0.1 \
  --port 7860 \
  --use-best-adapter
```

브라우저에서 접속:

```text
http://127.0.0.1:7860
```

서비스 UI는 실험용 평가 화면이 아니라, 질문과 답변 중심의 챗봇 형태로 정리했습니다.

## 평가 실행

최신 평가 기준은 `eval`입니다.

예시:

```bash
.venv/bin/python eval/evaluation/scripts/run_evaluation.py \
  --eval-dir outputs/eval/new_eval_inputs/phase34_gold_50 \
  --predictions outputs/generation/final_690_phase34_gold_qwen/126_service_route_v3_nonbudget_patch_123_budget_50_eval_predictions_eval_schema.jsonl \
  --output-dir outputs/eval/new_eval_126_full_ragas_phase34_openai_gold50 \
  --enable-ragas \
  --enable-domain \
  --domain-gold-path eval/evaluation/data/rfp_domain_gold_sample.jsonl \
  --enable-llm-judge \
  --llm-judge-mode api \
  --llm-judge-reference-mode evidence_only \
  --llm-judge-model gpt-4o-mini
```

Phase2 결과는 `phase2_*.md`가 아니라 아래 파일로 저장됩니다.

```text
ragas_summary.md
ragas_results.csv
```

## GitHub 업로드 주의

아래 항목은 Git에 올리지 않습니다.

```text
.env
.venv/
data/**
indexes/
outputs/
```

대용량 파일이나 API key가 올라가지 않도록 `.gitignore`에 포함되어 있습니다.

## 현재 한계

- Phase3 기준 예산/금액 정확성이 아직 낮습니다.
- RAGAS context precision/recall이 낮아 근거 context 품질 개선 여지가 있습니다.
- PEFT는 파이프라인은 동작하지만 학습 라벨 수가 부족해 최종 성능 개선의 핵심은 아니었습니다.

## 다음 작업

- 예산/금액 필드 구분 강화
- source_store final 값 검증 강화
- required_fields 계열 원문 표/항목 추출 개선
- PEFT용 정답형 라벨 추가 확보
- 서비스에 출처 보기 옵션 추가
