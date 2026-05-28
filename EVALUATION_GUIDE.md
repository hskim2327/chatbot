# RAG 평가 모듈 전체 사용 가이드

## 1. 문서 목적

이 문서는 RFP 특화 RAG 평가 모듈 사용법을 설명한다. 평가 모듈은 Phase 1~4로 구성되며, 검색 성능부터 RFP 도메인 정답 요소 평가, LLM Judge 기반 종합 평가까지 단계별로 확인할 수 있다.

현재 상태는 평가 로직 구현 완료 단계다. 실제 RAG pipeline 이식/결합과 production predictions JSONL 생성은 추후 진행한다. 팀원은 이 문서를 기준으로 평가 데이터 구성, 실행 명령, 결과 파일, API 설정 방법을 이해할 수 있다.

## 2. 전체 위치 요약

| 항목 | 경로 |
|---|---|
| 프로젝트 루트 | `/home/beomsoo/chatbot` |
| 평가 모듈 | `eval/evaluation/` |
| 실행 파일 | `eval/evaluation/scripts/run_evaluation.py` |
| 평가 코드 | `eval/evaluation/src/rag_eval/` |
| 정답지 | `eval/evaluation/data/` |
| 세부 문서 | `eval/evaluation/docs/` |
| 출력 | `eval/evaluation/outputs/eval/` |

## 3. 평가 모듈 폴더 구조

| 폴더 | 역할 |
|---|---|
| `eval/evaluation/` | RAG 평가 모듈 루트다. README, requirements, docs, scripts, src, tests, data, outputs를 포함한다. |
| `eval/evaluation/scripts/` | CLI 실행 진입점이 있는 폴더다. 핵심 entrypoint는 `run_evaluation.py`다. |
| `eval/evaluation/src/rag_eval/` | Phase 1~4 평가 로직이 들어 있는 Python package다. |
| `eval/evaluation/data/` | Phase 3 최종 gold set과 평가 기준 데이터가 있는 폴더다. |
| `eval/evaluation/docs/` | 평가 설계, metric guide, gold guide, API runbook 등 세부 문서가 있는 폴더다. |
| `eval/evaluation/tests/` | 평가 모듈 테스트가 있는 폴더다. |
| `eval/evaluation/outputs/eval/` | 평가 실행 결과 CSV/JSON/Markdown이 저장되는 기본 출력 폴더다. |
| `eval/evaluation/outputs/eval/experiment_logs/` | 실험별 누적 로그가 append-only CSV로 저장되는 폴더다. |

## 4. 핵심 파일 목록

### 실행 파일

| 파일 | 역할 |
|---|---|
| `eval/evaluation/scripts/run_evaluation.py` | 평가 CLI 진입점이다. 실제 로직은 `eval/evaluation/src/rag_eval/` 아래 모듈이 담당한다. |

### 설정/의존성

| 파일 | 역할 |
|---|---|
| `eval/evaluation/requirements.txt` | 평가 모듈 실행에 필요한 Python dependency 목록이다. |
| `eval/evaluation/.env.example` | Phase 4 LLM Judge API key와 model 설정 예시 파일이다. 실제 key는 들어 있지 않다. |

### 정답지/도메인 gold

| 파일 | 역할 |
|---|---|
| `eval/evaluation/data/rfp_domain_gold_sample.jsonl` | Phase 3 deterministic domain metric이 읽는 최종 gold JSONL이다. |
| `eval/evaluation/data/rfp_domain_gold_sample.xlsx` | 사람이 검토하기 쉬운 최종 gold Excel이다. |
| `eval/evaluation/data/rfp_domain_gold_sample_readable.csv` | 사람이 빠르게 열어볼 수 있는 최종 gold 요약 CSV다. |
| `eval/evaluation/data/rfp_domain_gold_sample_validation.csv` | 최종 gold set validation 결과다. |

### 주요 문서

| 파일 | 역할 |
|---|---|
| `EVALUATION_GUIDE.md` | 팀원이 가장 먼저 볼 전체 사용 가이드다. |
| `eval/evaluation/README.md` | 평가 모듈 내부 README다. |
| `eval/evaluation/docs/phase3_domain_metric_guide.md` | Phase 3 점수 계산 방식과 해석 기준을 설명한다. |
| `eval/evaluation/docs/rfp_domain_gold_sample_guide.md` | Phase 3 gold JSONL 구조와 영어 필드명을 설명한다. |
| `eval/evaluation/docs/phase4_llm_judge_api_runbook.md` | Phase 4 API mode를 실제로 검증할 때 따르는 실행 가이드다. |

## 5. 데이터 구성 설명

### predictions JSONL

`predictions JSONL`은 RAG 시스템이 생성해야 하는 평가 입력 파일이다. 실제 RAG pipeline 결합 후 생성된다.

필수 필드:

- `id`
- `question`
- `answer`
- `retrieved_contexts`

`retrieved_contexts` 권장 필드:

- `rank`
- `filename` 또는 `doc_id`
- `chunk_id`
- `score`
- `text`
- `metadata`

Phase 1은 `retrieved_contexts`에서 top-5 unique documents를 만든다. Phase 3와 Phase 4는 주로 `answer`와 `retrieved_contexts`의 문서/근거 정보를 사용한다.

### Phase 3 gold set

Phase 3 gold set은 `eval/evaluation/data/rfp_domain_gold_sample.jsonl`이다.

- 50개 hybrid gold set이다.
- Phase 3 deterministic domain metric에 사용한다.
- 예산, 필수 필드, 제출서류/입찰자격/마감일, 답변불가, 다중 문서 비교, 오타/구어체 견고성 평가 기준을 담고 있다.
- Phase 4 기본 `evidence_only` 모드에서는 사용하지 않는다.
- Phase 4 `gold_guided` 선택 모드에서만 보조적으로 사용할 수 있다.

### `.env`

`.env`는 API key와 LLM Judge 설정을 로컬에서 관리하는 파일이다.

- 실제 `.env`는 저장소에 포함하지 않는다.
- `eval/evaluation/.env.example`만 참고용으로 제공한다.
- API key는 코드, 문서, 채팅창, 로그에 쓰지 않는다.
- output과 experiment log에는 API key 값이 저장되지 않고 `api_key_present` boolean만 저장된다.

## 6. Phase 1~4 평가 구조

| Phase | 실행 flag | 핵심 평가 | 설명 |
|---|---|---|---|
| Phase 1 Retrieval Evaluation | 기본 실행 | `hit_at_5`, `mrr_at_5`, `ndcg_at_5` | 정답 문서가 top-5 unique documents 안에 검색됐는지 평가한다. |
| Phase 2 RAGAS Generation Evaluation | `--enable-ragas` | RAGAS 기본 evaluator | RAGAS 라이브러리의 기본 evaluator로 생성 품질을 평가한다. RAGAS 환경/API 설정이 필요할 수 있다. |
| Phase 3 RFP Domain Evaluation | `--enable-domain` | 예산, 필수 필드, 답변불가, 다중 문서 비교, 견고성 metric | `rfp_domain_gold_sample.jsonl` 기반 deterministic rule 평가다. |
| Phase 4 LLM Judge Evaluation | `--enable-llm-judge` | LLM Judge 총평가와 세부 진단 점수 | 기본 reference mode는 `evidence_only`다. `mock`, `dry_run`, `api` mode가 있다. 실제 총평가와 세부 진단 점수는 `api` mode에서 수행한다. |

각 Phase는 서로 대체 관계가 아니라 보완 관계다. Phase 1은 검색, Phase 2는 RAGAS 생성 품질, Phase 3는 RFP gold block 반영 여부, Phase 4는 evidence summary 기반 실무 유용성과 위험도를 본다.

## 7. 설치 방법

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

## 8. 기본 실행 방법

아래 예시에서 `<predictions.jsonl>`은 실제 RAG pipeline이 생성한 predictions JSONL 경로로 바꾼다.

### Phase 1만 실행

```bash
python eval/evaluation/scripts/run_evaluation.py --predictions <predictions.jsonl>
```

### Phase 1 + Phase 2

```bash
python eval/evaluation/scripts/run_evaluation.py --predictions <predictions.jsonl> --enable-ragas
```

### Phase 1 + Phase 3

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-domain `
  --domain-gold-path eval/evaluation/data/rfp_domain_gold_sample.jsonl
```

### Phase 1 + Phase 4 dry_run

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-llm-judge `
  --llm-judge-mode dry_run `
  --llm-judge-reference-mode evidence_only
```

### Phase 1 + Phase 4 API sample

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 1
```

### 최종 전체 평가 예시

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-ragas `
  --enable-domain `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --domain-gold-path eval/evaluation/data/rfp_domain_gold_sample.jsonl
```

최종 전체 평가는 반드시 Phase 4 `dry_run`과 API `sample-size 1~5` 검증 후 실행한다.

## 9. Phase 4 API key 입력 위치

API key는 코드에 쓰지 않는다. API key는 채팅창이나 문서에 붙여넣지 않는다. 실제 API key는 로컬 `.env` 파일에만 작성한다.

`.env.example`을 복사해 `.env`를 만든다.

```bash
cp eval/evaluation/.env.example eval/evaluation/.env
```

`.env` 예시는 다음과 같다.

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

- `your_api_key_here`는 실제 key가 아니라 placeholder다.
- 실제 문서에는 secret 형태의 key를 절대 쓰지 않는다.
- `.env`는 git에 올리지 않는다.
- output, log, experiment log에는 API key 값이 저장되지 않고 `api_key_present` boolean만 저장된다.

## 10. LLM Judge model 변경 방법

### 방법 1. `.env`에서 변경

```text
LLM_JUDGE_MODEL=원하는_모델명
```

### 방법 2. CLI에서 변경

```bash
python eval/evaluation/scripts/run_evaluation.py `
  --predictions <predictions.jsonl> `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-model 원하는_모델명
```

우선순위:

1. CLI `--llm-judge-model`
2. `.env`의 `LLM_JUDGE_MODEL`

주의:

- API mode에서는 model이 필수다.
- model을 바꾸면 Phase 4 점수 기준도 달라질 수 있으므로 experiment log에서 model명을 반드시 확인한다.
- 팀 공통 평가에서는 같은 model, prompt_version, schema_version, temperature를 사용해야 한다.

## 11. Phase 4 mode 설명

| mode | 실제 API 호출 | 목적 | 주의 |
|---|---|---|---|
| `mock` | 없음 | deterministic dummy judge 결과 생성. 개발/테스트용이다. | 실제 품질 점수로 해석하면 안 된다. |
| `dry_run` | 없음 | Judge input JSONL만 생성한다. API 실행 전 payload 확인용이다. | API 실행 전에 먼저 확인하는 것을 권장한다. |
| `api` | 있음 | 실제 LLM API 호출로 Judge 평가를 수행한다. | 비용이 발생할 수 있다. API key와 model이 필요하며 sample-size 1부터 검증한다. |

## 12. Phase 4 reference mode 설명

### `evidence_only`

- 기본값이다.
- `question`, `rag_answer`, `source_docs`, `retrieved_evidence_summaries`만 사용한다.
- gold summary를 사용하지 않는다.
- 최종 기본 평가 모드다.

### `gold_guided`

- 선택 모드다.
- `domain_gold_summary` 또는 `ground_truth_answer_summary`를 포함할 수 있다.
- Phase 3와 비교 분석하거나 Judge 안정성을 검증할 때만 사용한다.
- 기본 평가 결과와 섞지 않는다.

## 13. 출력 파일 설명

기본 출력 경로는 `eval/evaluation/outputs/eval/`이다.

### 공통 출력

| 파일 | 언제 보는가 |
|---|---|
| `eval_results.csv` | 문항별 Phase 1 검색 결과를 볼 때 |
| `eval_summary.md` | 전체 Retrieval 요약을 빠르게 볼 때 |
| `experiment_logs/phase1_retrieval_experiments.csv` | Retrieval 실험을 누적 비교할 때 |
| `failure_analysis_experiments.csv` | 실패 분석 실험 로그를 볼 때 |

### Phase 2

| 파일 | 언제 보는가 |
|---|---|
| `ragas_results.csv` | 문항별 RAGAS 점수 또는 오류를 볼 때 |
| `experiment_logs/phase2_ragas_experiments.csv` | RAGAS 실험을 누적 비교할 때 |

### Phase 3

| 파일 | 언제 보는가 |
|---|---|
| `phase3_domain_results.csv` | 문항별 RFP domain metric을 볼 때 |
| `phase3_domain_summary.md` | Phase 3 전체 요약을 볼 때 |
| `phase3_domain_by_task.csv` | task_family별 평균을 볼 때 |
| `phase3_domain_failure_cases.csv` | 낮은 점수나 오류 문항을 볼 때 |
| `experiment_logs/phase3_domain_experiments.csv` | Phase 3 실험을 누적 비교할 때 |

### Phase 4

| 파일 | 언제 보는가 |
|---|---|
| `phase4_llm_judge_inputs.jsonl` | API 호출 전 Judge 입력 payload를 검토할 때 |
| `phase4_llm_judge_results.csv` | row-level Judge 점수와 후처리 필드를 볼 때 |
| `phase4_llm_judge_results.json` | nested Judge output 구조를 확인할 때 |
| `phase4_llm_judge_summary.md` | 평균 점수, risk 분포, error count를 볼 때 |
| `phase4_llm_judge_failure_cases.csv` | parse/validation/API failure를 볼 때 |
| `experiment_logs/phase4_llm_judge_experiments.csv` | Phase 4 실험을 누적 비교할 때 |

## 14. 결과 해석 방법

### Phase 1

- `hit_at_5`: top-5 unique documents 안에 정답 문서가 하나라도 있으면 1이다.
- `mrr_at_5`: 첫 번째 정답 문서가 앞에 있을수록 높다.
- `ndcg_at_5`: 여러 정답 문서가 상위권에 배치될수록 높다.

### Phase 3

- `phase3_task_score`: task_family별 대표 domain metric이다.
- task별 평균은 `phase3_domain_by_task.csv`에서 본다.
- 실패 문항은 `phase3_domain_failure_cases.csv`에서 확인한다.

### Phase 4

- `judge_overall_score`: LLM이 직접 낸 참고용 총평 점수다.
- `calculated_overall_score`: 코드가 subscore 가중합과 cap rule로 계산한 공식 Phase 4 종합 점수다.
- `overall_label`: `calculated_overall_score` 구간 라벨이다.
- subscore 평균: 실무 유용성, 완전성, 근거성, 숫자/사실 정확성, 구조 명확성, 위험 통제 수준을 본다.
- `risk_level`: 실무 위험 수준이다.
- `hallucination_risk`: 문서에 없는 내용 단정 위험이다.
- `needs_human_review`: 사람이 추가 확인해야 하는지 여부다.
- `score_cap_applied`: 위험 조건 때문에 calculated score 상한이 적용됐는지 여부다.
- `score_disagreement_warning`: LLM 총평 점수와 코드 계산 점수 차이가 큰지 여부다.

Phase 4에서 공식적으로 비교에 사용할 점수는 `calculated_overall_score`다. `judge_overall_score`는 참고값이다.

## 15. 권장 실행 순서

실제 RAG predictions가 준비되면 다음 순서를 권장한다.

1. Phase 1만 실행해 predictions 구조를 확인한다.
2. Phase 3 실행으로 id/gold 매칭을 확인한다.
3. Phase 4 `dry_run`으로 judge input을 확인한다.
4. Phase 4 `api`를 `sample-size 1`로 실행한다.
5. Phase 4 `api`를 `sample-size 3~5`로 확대한다.
6. 필요하면 Phase 2 RAGAS를 실행한다.
7. 최종 전체 평가를 실행한다.
8. experiment log 기준으로 baseline 수치를 확정한다.

## 16. 자주 생기는 문제와 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| predictions 파일 경로 오류 | `--predictions` 경로가 잘못됨 | 경로를 따옴표로 감싸고 실제 파일 존재 여부를 확인한다. |
| id가 gold set과 매칭되지 않음 | predictions의 `id`와 gold JSONL의 `id`가 다름 | predictions 생성 단계에서 canonical id를 유지한다. |
| `retrieved_contexts`가 비어 있음 | RAG pipeline 검색 결과 저장 누락 | 검색 결과를 JSONL에 포함하도록 pipeline exporter를 조정한다. |
| `filename`/`doc_id`가 없음 | retrieved context 문서 식별자 누락 | 최소 하나는 반드시 저장한다. filename이 있으면 filename을 우선한다. |
| RAGAS import error | dependency 또는 환경 설정 문제 | `python -m pip install -r eval/evaluation/requirements.txt`를 다시 실행한다. |
| API key 없음 | 로컬 `.env` 또는 OS 환경변수 미설정 | `OPENAI_API_KEY`를 로컬 `.env`에만 설정한다. |
| `LLM_JUDGE_MODEL` 없음 | API mode model 미설정 | `.env` 또는 `--llm-judge-model`로 model을 지정한다. |
| structured output fallback 발생 | SDK/모델 structured output 호환성 문제 | `phase4_llm_judge_api_runbook.md` 기준으로 fallback과 validation error를 확인한다. |
| parse_error 발생 | LLM 응답 JSON 파싱 실패 | sample-size를 키우지 말고 failure case를 먼저 확인한다. |
| validation_error 발생 | score 범위, 필수 필드, evidence_refs 오류 | `phase4_llm_judge_failure_cases.csv`에서 schema 오류를 확인한다. |
| timeout 발생 | API 응답 지연 또는 네트워크 문제 | sample-size를 줄이고 timeout 설정을 확인한다. |
| `.env`가 git에 올라갈 위험 | 로컬 secret 파일 관리 실수 | `.gitignore`와 commit 대상 파일을 확인한다. |
| Phase 4 mock 점수를 실제 점수로 착각 | mock mode는 dummy output | mock 결과는 개발/테스트 흐름 확인용으로만 본다. |

## 17. 보안 주의사항

- API key를 코드, 문서, 채팅, 로그에 쓰지 않는다.
- 실제 `.env`는 공유하지 않는다.
- `.env.example`만 공유한다.
- 원본 RFP 전문이나 민감 정보가 출력 파일에 들어가지 않도록 주의한다.
- Phase 4 input에는 긴 원문이 아니라 evidence summary만 넣는 정책을 유지한다.
- API mode 실행 전 output에 secret이 들어가는지 확인한다.

## 18. 팀원이 봐야 할 최소 문서

| 순서 | 문서 | 보는 이유 |
|---:|---|---|
| 1 | `EVALUATION_GUIDE.md` | 전체 평가 구조와 실행 흐름을 한 번에 이해하기 위해 |
| 3 | `eval/evaluation/README.md` | 평가 모듈 내부 README와 CLI 예시를 확인하기 위해 |
| 4 | `eval/evaluation/docs/phase3_domain_metric_guide.md` | Phase 3 점수 계산 방식과 해석 기준을 이해하기 위해 |
| 5 | `eval/evaluation/docs/rfp_domain_gold_sample_guide.md` | Phase 3 정답지 JSONL 구조와 필드 의미를 이해하기 위해 |
| 6 | `eval/evaluation/docs/phase4_llm_judge_api_runbook.md` | 실제 LLM Judge API mode 실행 전 안전 절차를 확인하기 위해 |
