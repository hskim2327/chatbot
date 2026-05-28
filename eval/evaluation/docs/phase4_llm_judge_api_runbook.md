# Phase 4 LLM Judge API Mode 실행 가이드

## 1. 문서 목적

이 문서는 Phase 4 LLM Judge의 `api` mode를 팀원이 안전하게 검증하기 위한 실행 가이드다.

현재 Phase 4는 다음 상태다.

- `mock` mode 구현 완료
- `dry_run` mode 구현 완료
- OpenAI API adapter 구현 완료
- fake client 기반 테스트 통과
- 실제 OpenAI API 호출은 아직 미검증

따라서 실제 `api` mode는 반드시 소량 `sample-size`부터 검증한다. 이 문서는 실제 API key 값을 쓰거나 저장하지 않는다.

## 2. 실행 전 준비사항

1. 평가 모듈 의존성을 설치한다.
2. `eval/evaluation/.env.example`을 참고해 로컬에서만 `eval/evaluation/.env`를 만든다.
3. 로컬 `.env` 또는 OS 환경변수에 `OPENAI_API_KEY`를 설정한다.
4. `LLM_JUDGE_MODEL`을 반드시 설정한다. `api` mode에서는 model이 필수다.
5. 실제 `.env`는 커밋하지 않는다.
6. API key 값은 로그, 결과 CSV/JSON, summary, experiment log, 문서에 남기지 않는다.
7. API mode는 비용이 발생할 수 있으므로 처음부터 전체 평가를 실행하지 않는다.

`.env.example`에는 값이 비어 있는 placeholder만 둔다. 실제 key는 로컬 `.env`에만 작성한다.

## 3. 권장 실행 순서

1. 기존 테스트를 실행한다.
2. `run_evaluation.py --help`로 CLI 옵션을 확인한다.
3. `dry_run`으로 judge input을 생성한다.
4. `phase4_llm_judge_inputs.jsonl`을 검토한다.
5. `api` mode를 `--llm-judge-sample-size 1`로 실행한다.
6. 결과 CSV/JSON/summary/failure_cases를 확인한다.
7. `structured_output_used`와 `fallback_json_mode_used`를 확인한다.
8. `parse_error`, `validation_error`, `timeout_error`를 확인한다.
9. 문제가 없으면 `sample-size 3~5`로 확대한다.
10. 최종적으로 전체 평가를 실행한다.

권장 확대 순서는 `1 -> 3~5 -> 10 -> 전체`다.

## 4. PowerShell 실행 예시

아래 예시는 Windows PowerShell 기준이다. `<PREDICTIONS_JSONL>`은 실제 RAG pipeline이 만든 predictions JSONL 경로로 바꾼다.

### 4-1. 의존성 설치

```powershell
python -m pip install -r eval/evaluation/requirements.txt
```

### 4-2. 테스트 실행

```powershell
python -m pytest eval/evaluation/tests -q
```

### 4-3. CLI 옵션 확인

```powershell
python eval/evaluation/scripts/run_evaluation.py --help
```

### 4-4. dry_run으로 Judge input 생성

```powershell
python eval/evaluation/scripts/run_evaluation.py `
  --predictions "<PREDICTIONS_JSONL>" `
  --enable-llm-judge `
  --llm-judge-mode dry_run `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 5
```

생성된 `eval/evaluation/outputs/eval/phase4_llm_judge_inputs.jsonl`을 먼저 확인한다.

### 4-5. API mode sample-size 1 실행

```powershell
python eval/evaluation/scripts/run_evaluation.py `
  --predictions "<PREDICTIONS_JSONL>" `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 1
```

### 4-6. API mode sample-size 3~5 실행

```powershell
python eval/evaluation/scripts/run_evaluation.py `
  --predictions "<PREDICTIONS_JSONL>" `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 5
```

### 4-7. strict mode 실행 예시

strict mode는 API 검증이 안정화된 뒤 사용한다. 실패 시 non-zero exit code가 반환될 수 있다.

```powershell
python eval/evaluation/scripts/run_evaluation.py `
  --predictions "<PREDICTIONS_JSONL>" `
  --enable-llm-judge `
  --llm-judge-mode api `
  --llm-judge-reference-mode evidence_only `
  --llm-judge-sample-size 3 `
  --require-llm-judge
```

## 5. API mode 실행 전후 확인할 출력 파일

기본 출력 경로는 `eval/evaluation/outputs/eval/`이다.

| 파일 | 확인 목적 |
|---|---|
| `phase4_llm_judge_inputs.jsonl` | LLM Judge에 전달될 입력 payload 확인. 원본 RFP 전문, 긴 table, Phase 1/2/3 점수, API key가 없어야 한다. |
| `phase4_llm_judge_results.csv` | row-level Judge 결과 확인. `calculated_overall_score`, score cap, parse/validation error를 본다. |
| `phase4_llm_judge_results.json` | nested output 원형에 가까운 결과 확인. schema 구조 디버깅에 사용한다. |
| `phase4_llm_judge_summary.md` | 전체 요약 확인. 평균 점수, risk 분포, error count, structured/fallback 사용 여부를 본다. |
| `phase4_llm_judge_failure_cases.csv` | 실패 또는 사람 검토 필요 row 확인. 비어 있거나 원인이 명확해야 한다. |
| `experiment_logs/phase4_llm_judge_experiments.csv` | append-only 실험 로그 확인. `api_key_present`는 boolean만 기록되어야 한다. |

## 6. Structured Outputs 호환성 확인 기준

API mode 실행 후 summary와 results에서 다음을 확인한다.

- `structured_output_used=True`이면 이상적이다.
- `fallback_json_mode_used=True`이면 SDK 또는 모델 호환성 때문에 JSON fallback을 사용한 것이다. 이 경우 schema 강제력이 약할 수 있으므로 local validation 결과를 더 주의해서 본다.
- `parse_error_count=0`인지 확인한다.
- `validation_error_count=0`인지 확인한다.
- `timeout_count=0`인지 확인한다.
- `failed_count=0`인지 확인한다.

fallback을 사용했더라도 `parse_error_count=0`, `validation_error_count=0`, `failed_count=0`이면 소량 검증은 계속 진행할 수 있다. 다만 최종 보고서에는 fallback 사용 사실을 남긴다.

## 7. 실패 시 대응

### API key 없음

증상:

- summary 또는 failure case에 API key 설정 오류가 기록된다.
- `api_key_present=False`로 기록된다.

대응:

- 로컬 `eval/evaluation/.env` 또는 OS 환경변수에 `OPENAI_API_KEY`가 있는지 확인한다.
- key 값을 결과 파일이나 문서에 복사하지 않는다.
- `--require-llm-judge`가 켜져 있으면 non-zero exit code가 정상 동작일 수 있다.

### model 없음

증상:

- model 설정 오류가 기록된다.

대응:

- `LLM_JUDGE_MODEL`을 로컬 `.env`에 설정하거나 `--llm-judge-model` CLI 옵션을 사용한다.
- 모델명은 기록 가능하지만 API key 값은 기록하지 않는다.

### Structured Output TypeError

증상:

- `fallback_json_mode_used=True`가 된다.

대응:

- 사용 중인 OpenAI SDK와 모델이 Structured Outputs 요청 형식을 지원하는지 확인한다.
- fallback 상태에서는 `validation_error_count`와 `parse_error_count`를 반드시 확인한다.
- fallback이 반복되면 SDK 버전과 모델 선택을 점검한다.

### fallback으로 갔지만 validation error 발생

증상:

- `fallback_json_mode_used=True`
- `validation_error_count > 0`

대응:

- `phase4_llm_judge_failure_cases.csv`에서 누락 필드, 1~5 범위 위반, enum 위반을 확인한다.
- sample-size를 더 키우지 말고 해당 오류가 재현되는지 확인한다.
- schema 또는 prompt 수정이 필요한지 별도 이슈로 분리한다.

### parse error 발생

증상:

- `parse_error_count > 0`

대응:

- LLM 응답이 JSON이 아니거나 잘린 경우일 수 있다.
- `failure_cases.csv`의 짧은 오류 메시지를 확인한다.
- 긴 raw response 전체를 저장하지 않는다.
- sample-size를 확대하지 않는다.

### timeout 발생

증상:

- `timeout_count > 0`

대응:

- 네트워크 상태, 모델 응답 지연, `LLM_JUDGE_TIMEOUT_SECONDS` 설정을 확인한다.
- retry가 1회 수행되었는지 `retry_count`를 확인한다.
- timeout이 반복되면 sample-size를 낮추고 다시 실행한다.

### rate limit 발생

증상:

- failure case에 rate limit 또는 transient API error가 기록될 수 있다.
- `retry_count`가 증가할 수 있다.

대응:

- 잠시 대기 후 더 작은 sample-size로 재실행한다.
- 전체 평가를 바로 실행하지 않는다.
- 필요하면 모델 또는 계정 제한을 확인한다.

### calculated_overall_score 공백 발생

증상:

- `phase4_llm_judge_results.csv`에서 `calculated_overall_score`가 비어 있다.

대응:

- parse error 또는 validation error 여부를 먼저 확인한다.
- score range가 1~5를 벗어났거나 필수 subscore가 누락되었을 가능성이 있다.
- 해당 row는 공식 해석 전에 사람 검토가 필요하다.

### evidence_refs validation error 발생

증상:

- validation error에 evidence reference index 범위 문제가 기록된다.

대응:

- Judge output의 `evidence_refs`가 `retrieved_evidence_summaries`의 0-based index 범위 안인지 확인한다.
- `phase4_llm_judge_inputs.jsonl`에서 evidence 개수를 확인한다.
- 반복되면 prompt 또는 schema 보완 이슈로 분리한다.

## 8. 비용과 안전장치

- 처음부터 전체 평가를 실행하지 않는다.
- `sample-size 1 -> 3~5 -> 10 -> 전체` 순서로 확대한다.
- API mode는 비용이 발생할 수 있다.
- 실행 전 predictions row 수를 확인한다.
- 실행 후 experiment log의 `judged_count`를 확인한다.
- output 파일에 API key 값이 없는지 확인한다.
- `phase4_llm_judge_inputs.jsonl`에 원본 RFP 전문, 긴 table, source_store 전체가 들어가지 않았는지 확인한다.

간단한 row 수 확인 예시:

```powershell
(Get-Content "<PREDICTIONS_JSONL>").Count
```

API key 문자열 노출 여부를 볼 때는 실제 key를 화면에 출력하지 말고, 대표적인 secret prefix나 빈 placeholder만 점검한다.

```powershell
Select-String -Path "eval/evaluation/outputs/eval/*" -Pattern "sk-" -SimpleMatch
```

## 9. 최종 API 검증 완료 기준

최소한 다음 기준을 만족해야 API mode를 팀 내 검증 완료로 볼 수 있다.

- `sample-size 3~5`에서 exit code 0
- `parse_error_count=0`
- `validation_error_count=0`
- `timeout_count=0`
- `failed_count=0`
- `structured_output_used=True` 또는 fallback 사용 사유가 명확함
- `phase4_llm_judge_results.csv`에 `calculated_overall_score`가 존재함
- `phase4_llm_judge_summary.md`에 평균 점수와 risk 분포가 존재함
- `phase4_llm_judge_failure_cases.csv`가 비어 있거나 원인이 명확함
- API key 값이 어떤 output에도 없음

위 기준을 만족한 뒤에만 `sample-size 10` 또는 전체 평가로 확대한다.

## 10. 운영 원칙

- Phase 4는 Phase 1/2/3 공식 점수를 대체하지 않는 보조 평가다.
- 기본 reference mode는 `evidence_only`다.
- `evidence_only` prompt에는 `domain_gold_summary`, `ground_truth_answer_summary`, Phase 1/2/3 metric, `warning_resolution_status`를 넣지 않는다.
- 실제 API 실행 전에는 반드시 `dry_run` 산출물을 먼저 확인한다.
- API key 값은 어떤 파일에도 저장하지 않는다.
- 실제 API 검증 결과는 비용, 모델명, prompt/schema version, sample-size와 함께 해석한다.
