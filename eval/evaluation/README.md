# RAG 평가 모듈 README

## 1. 평가 모듈 목적

`eval/evaluation/`은 AI 중급 프로젝트의 RFP 특화 RAG 평가 모듈이다. 이 모듈은 Phase 1~4 평가 로직을 포함한다.

- Phase 1: 검색 성능 평가
- Phase 2: RAGAS 기반 생성 품질 평가
- Phase 3: RFP 도메인 특화 deterministic 평가
- Phase 4: evidence-only LLM Judge 기반 종합 평가

현재는 평가 로직 구현이 완료된 상태다. 실제 RAG pipeline 이식/결합과 production predictions JSONL 생성은 추후 진행한다.

이 README는 평가 모듈 내부에서 빠르게 확인하는 요약 문서다. 상세 사용법은 프로젝트 루트의 `EVALUATION_GUIDE.md`를 먼저 본다.

## 2. 먼저 볼 문서

| 문서 | 역할 |
|---|---|
| `EVALUATION_GUIDE.md` | 프로젝트 루트에 있는 전체 사용 가이드다. 데이터 구성, 실행 명령, API 설정, 결과 해석을 한 번에 설명한다. |
| `eval/evaluation/docs/phase3_domain_metric_guide.md` | Phase 3 점수 계산 방식과 해석 기준을 설명한다. |
| `eval/evaluation/docs/rfp_domain_gold_sample_guide.md` | Phase 3 gold JSONL 구조와 영어 필드명을 설명한다. |
| `eval/evaluation/docs/phase4_llm_judge_api_runbook.md` | Phase 4 API mode를 실제로 검증할 때 따르는 실행 가이드다. |

과거 설계 문서나 리서치 노트는 구현 근거로 의미가 있지만, 기본 사용 안내는 위 문서를 우선한다. 오래된 Phase 4 계획서는 cleanup 시 archive 대상으로 검토한다.

## 3. 폴더 구조

| 폴더 | 역할 |
|---|---|
| `eval/evaluation/scripts/` | CLI 실행 진입점이 있다. 핵심 파일은 `run_evaluation.py`다. |
| `eval/evaluation/src/rag_eval/` | Phase 1~4 평가 로직이 들어 있는 Python package다. |
| `eval/evaluation/tests/` | 평가 모듈 테스트가 들어 있다. |
| `eval/evaluation/data/` | Phase 3 최종 gold set과 validation 파일이 들어 있다. |
| `eval/evaluation/docs/` | metric guide, gold guide, API runbook가 들어 있다. |
| `eval/evaluation/outputs/eval/` | 평가 실행 결과가 저장되는 기본 출력 폴더다. |
| `eval/evaluation/outputs/eval/experiment_logs/` | 실험별 누적 로그가 append-only CSV로 저장되는 폴더다. |

## 4. Phase 1~4 요약

| Phase | 실행 방식 | 주요 평가 내용 | 핵심 출력/지표 |
|---|---|---|---|
| Phase 1 Retrieval Evaluation | 기본 실행 | 정답 문서가 top-5 unique documents 안에 검색됐는지 평가한다. | `hit_at_5`, `mrr_at_5`, `ndcg_at_5` |
| Phase 2 RAGAS Generation Evaluation | `--enable-ragas` | RAGAS 라이브러리의 기본 evaluator로 생성 품질을 평가한다. | RAGAS results |
| Phase 3 RFP Domain Evaluation | `--enable-domain` | `rfp_domain_gold_sample.jsonl` 기반으로 RFP 실무 정답 요소를 rule-based로 평가한다. | `phase3_task_score`, task별 domain metric |
| Phase 4 LLM Judge Evaluation | `--enable-llm-judge` | evidence summary 기반으로 실무 유용성, 근거성, 위험도를 LLM Judge가 평가한다. | `calculated_overall_score`, subscores, risk signals |

각 Phase는 서로 대체 관계가 아니다. Phase 1은 검색, Phase 2는 RAGAS 생성 품질, Phase 3는 RFP gold block 반영 여부, Phase 4는 evidence 기반 종합 품질과 위험도를 본다.

## 5. 설치와 테스트

프로젝트 루트에서 실행한다.

```bash
cd /home/beomsoo/chatbot
```

의존성을 설치한다.

```bash
python -m pip install -r eval/evaluation/requirements.txt
```

테스트를 실행한다.

```bash
python -m pytest eval/evaluation/tests -q
```

CLI 옵션을 확인한다.

```bash
python eval/evaluation/scripts/run_evaluation.py --help
```

## 6. 실행 예시

아래 예시에서 `<predictions.jsonl>`은 실제 RAG pipeline이 생성한 predictions JSONL 경로로 바꾼다.

### Phase 1만 실행

```bash
python eval/evaluation/scripts/run_evaluation.py --predictions <predictions.jsonl>
```

### Phase 1 + Phase 3

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-domain `
  --domain-gold-path eval/evaluation/data/rfp_domain_gold_sample.jsonl
```

### Phase 4 dry_run

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-llm-judge `
  --llm-judge-mode dry_run `
  --llm-judge-reference-mode evidence_only
```

### Phase 4 API sample-size 1

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 1
```

더 자세한 실행법과 결과 해석은 프로젝트 루트의 `EVALUATION_GUIDE.md`를 본다. Phase 4 API mode는 비용이 발생할 수 있으므로 `dry_run`과 작은 sample-size 검증 후 실행한다.

## 7. API key / model 설정

Phase 4 API mode를 사용하려면 로컬에서만 `eval/evaluation/.env`를 만든다. 실제 `.env`는 저장소에 포함하지 않는다.

`eval/evaluation/.env.example`을 참고해 로컬 `.env`를 만든다.

```bash
cp eval/evaluation/.env.example eval/evaluation/.env
```

예시:

```text
OPENAI_API_KEY=your_api_key_here
LLM_JUDGE_PROVIDER=openai
LLM_JUDGE_MODEL=your_model_here
LLM_JUDGE_TEMPERATURE=0
LLM_JUDGE_MAX_INPUT_CHARS=6000
LLM_JUDGE_TIMEOUT_SECONDS=60
LLM_JUDGE_PROMPT_VERSION=phase4_judge_v1
LLM_JUDGE_SCHEMA_VERSION=phase4_judge_schema_v1
```

주의:

- `your_api_key_here`와 `your_model_here`는 placeholder다.
- API key는 코드, 문서, 채팅, 로그, 결과 파일에 쓰지 않는다.
- 실제 `.env`는 공유하거나 커밋하지 않는다.
- output과 experiment log에는 API key 값이 아니라 `api_key_present` 여부만 기록한다.

LLM Judge model은 두 방식으로 지정할 수 있다.

1. `.env`에서 `LLM_JUDGE_MODEL` 설정
2. CLI에서 `--llm-judge-model` 지정

CLI 옵션이 `.env`보다 우선한다. 팀 공통 비교 실험에서는 같은 model, prompt_version, schema_version, temperature를 맞춘다.

Phase 4 API mode 절차는 `eval/evaluation/docs/phase4_llm_judge_api_runbook.md`를 따른다.

## 8. 출력과 실험 로그

평가 결과는 기본적으로 `eval/evaluation/outputs/eval/`에 저장된다.

주요 출력:

- `eval_results.csv`
- `eval_summary.md`
- `ragas_results.csv`
- `phase3_domain_results.csv`
- `phase3_domain_summary.md`
- `phase4_llm_judge_inputs.jsonl`
- `phase4_llm_judge_results.csv`
- `phase4_llm_judge_summary.md`
- `phase4_llm_judge_failure_cases.csv`

실험 로그는 `eval/evaluation/outputs/eval/experiment_logs/`에 append-only 방식으로 저장된다. baseline 비교와 실험 간 성능 추적은 experiment log를 기준으로 한다.

평가 출력물은 기본적으로 gitignore 대상이며, 필요한 요약만 별도로 공유한다.

## 9. 보안 주의사항

- API key, SSH key, 개인정보를 코드/문서/로그/결과 파일에 저장하지 않는다.
- 실제 `.env`는 커밋하지 않는다.
- 원본 RFP 전문, 긴 table, source_store 전체를 push하지 않는다.
- Phase 4 input에는 긴 원문 대신 짧은 evidence summary를 사용한다.
- `eval/evaluation/outputs/eval/` 아래 output 파일은 기본적으로 gitignore 대상이다.
- Phase 4 `mock` mode 결과는 실제 품질 점수가 아니므로 보고서의 최종 성능 수치로 쓰지 않는다.
