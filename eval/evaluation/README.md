# RAG 평가 모듈 README

## 1. 이 폴더의 목적

`evaluation/` 폴더는 AI 중급 프로젝트의 RAG 평가 전용 모듈이다. 프로젝트 본체의 RAG 파이프라인 코드와 평가 코드를 분리해, 팀원이 평가 로직을 독립적으로 확인하고 실행할 수 있도록 구성했다.

이 폴더는 다음 역할을 담당한다.

- Phase 1 검색 성능 평가
- Phase 2 RAGAS 기반 생성 품질 평가
- 실패 케이스 분석
- 실험별 성능 변화 추적을 위한 누적 로그 저장

평가 정책은 프로젝트 전체에서 동일하게 유지한다. 검색 성능 지표는 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`만 사용하고, RAGAS 평가는 기본 evaluator 방식만 사용한다.

문서 역할은 다음처럼 구분한다.

- `README.md`: 팀원이 평가 모듈의 목적, 구조, 실행 방법을 이해하기 위한 설명서
- `AGENTS.md`: Codex가 이 프로젝트와 평가 모듈을 수정할 때 따라야 하는 작업 지침서

프로젝트 루트의 `AGENTS.md`는 전체 공통 지침이고, `evaluation/AGENTS.md`는 RAG 평가 모듈 전용 지침이다.

## 2. 전체 폴더 구조

```text
evaluation/
  README.md
  AGENTS.md
  requirements.txt
  docs/
    evaluation_plan.md
    evaluation_refactor_plan.md
  scripts/
    run_evaluation.py
  src/
    rag_eval/
      __init__.py
      config.py
      schemas.py
      loaders.py
      normalization.py
      retrieval_metrics.py
      ragas_evaluator.py
      aggregation.py
      reports.py
      experiment_logger.py
      path_utils.py
      runner.py
  tests/
    conftest.py
    test_loaders.py
    test_normalization.py
    test_retrieval_metrics.py
    test_experiment_logger.py
    test_runner.py
  outputs/
    eval/
      .gitkeep
```

각 항목의 역할은 다음과 같다.

- `README.md`: 평가 모듈 사용법과 정책 설명
- `requirements.txt`: 평가 모듈 실행에 필요한 Python dependency
- `docs/`: 평가 설계 문서와 리팩토링 계획서
- `scripts/run_evaluation.py`: CLI 실행 진입점
- `src/rag_eval/`: 실제 평가 로직 패키지
- `tests/`: 평가 모듈 테스트
- `outputs/eval/`: 평가 결과와 실험 로그 기본 출력 위치

## 3. 평가 전체 흐름

평가 스크립트는 다음 순서로 동작한다.

1. eval CSV를 로드한다.
2. predictions JSONL을 로드한다.
3. `retrieved_contexts`를 `rank` 기준으로 정렬한다.
4. `filename`을 우선 사용하고, 없을 때만 `doc_id`로 문서를 식별한다.
5. 같은 문서가 여러 chunk로 검색되면 중복 제거하여 top-5 unique documents를 만든다.
6. `Hit@5`, `MRR@5`, `nDCG@5`를 계산한다.
7. `--enable-ragas`가 있으면 RAGAS 평가를 실행한다.
8. 실패 케이스를 분석한다.
9. run별 리포트를 저장한다.
10. experiment log CSV에 append한다.

기본 실행은 Phase 1 검색 성능 평가만 수행한다. RAGAS는 사용자가 `--enable-ragas`를 줄 때만 실행된다.

## 4. Phase 1: 검색 성능 평가

Phase 1은 document-level retrieval evaluation이다. 즉 chunk 단위가 아니라 문서 단위로 정답 문서가 검색되었는지 평가한다.

사용하는 지표는 다음 세 개뿐이다.

- `hit_at_5`
- `mrr_at_5`
- `ndcg_at_5`

공식 `top_k`는 5다. 같은 문서의 여러 chunk가 검색되면 하나의 문서로 중복 제거한다.

`ground_truth_docs`가 비어 있는 문항은 `NaN`으로 기록하고 평균 계산에서 제외한다.

### Hit@5

top-5 unique documents 안에 정답 문서가 하나라도 있으면 1, 없으면 0이다.

### MRR@5

첫 번째 정답 문서가 얼마나 앞에 나왔는지 보는 지표다. 정답 문서가 1위면 1.0, 2위면 0.5, 3위면 약 0.333이다.

### nDCG@5

정답 문서들이 상위권에 얼마나 잘 배치됐는지 보는 지표다. 다중 정답 문서 질문에서 여러 정답 문서가 앞쪽에 있을수록 점수가 높다.

## 5. Phase 2: RAGAS 기반 생성 품질 평가

Phase 2는 RAGAS 라이브러리를 고정 사용한다. 호출 방식은 강의 예시와 같은 기본 evaluator 방식이다.

```python
evaluate(dataset, metrics=[...])
```

custom llm, custom embeddings, 별도 judge backend adapter는 주입하지 않는다.

RAGAS metric 후보는 다음이다.

- `faithfulness`
- `answer_relevancy` 또는 RAGAS 버전에 따른 `response_relevancy`
- `context_precision`
- `context_recall`

Phase 2는 `--enable-ragas`가 있을 때만 실행된다.

`--require-ragas`는 최종 제출용 strict mode다. 이 옵션이 있으면 RAGAS 실패 시 가능한 결과 파일을 저장한 뒤 non-zero exit code로 종료한다.

RAGAS 실패는 `ragas_error`에 기록한다. RAGAS 실패가 Phase 1 결과 저장을 막지 않도록 설계되어 있다.

## 6. 입력 파일 형식

### eval CSV 필수 컬럼

eval CSV에는 다음 컬럼이 필요하다.

- `id`
- `type`
- `difficulty`
- `question`
- `ground_truth_answer`
- `ground_truth_docs`
- `metadata_filter`
- `history`

`ground_truth_docs`, `metadata_filter`, `history`는 문자열로 저장된 list/dict일 수 있으므로 내부에서 파싱한다.

### predictions JSONL 필수 필드

predictions JSONL은 한 줄에 한 문항의 예측 결과를 저장한다.

필수 필드는 다음이다.

- `id`
- `question`
- `answer`
- `retrieved_contexts`
- `latency_ms`
- `model_name`
- `embedding_model`
- `retriever_config`

`retrieved_contexts` 안의 필드는 다음이다.

- `rank`
- `filename` 또는 `doc_id`
- `chunk_id`
- `score`
- `text`
- `metadata`

### predictions JSONL 예시

아래는 형식 설명을 위한 더미 예시다. 원본 RFP 본문을 길게 넣지 않는다.

```json
{"id":"Q001","question":"예산은 얼마인가요?","answer":"문서 기준 예산은 1,000원입니다.","retrieved_contexts":[{"rank":1,"filename":"샘플문서.hwp","chunk_id":"sample-001","score":0.91,"text":"짧은 더미 근거 문장입니다.","metadata":{"agency":"샘플기관"}}],"latency_ms":1234,"model_name":"local-model","embedding_model":"embedding-model","retriever_config":{"chunk_size":800,"chunk_overlap":100,"top_k":5,"retriever_type":"dense","reranker":false}}
```

## 7. 실행 방법

아래 명령은 프로젝트 루트에서 실행한다.

### Windows PowerShell: Phase 1만 실행

```powershell
python eval/scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir eval/evaluation/outputs/eval ^
  --experiment-name "baseline_retrieval_only"
```

### Windows PowerShell: Phase 1 + RAGAS 실행

```powershell
python eval/scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir eval/evaluation/outputs/eval ^
  --enable-ragas ^
  --experiment-name "baseline_with_ragas"
```

### Windows PowerShell: 최종 제출용 strict mode

```powershell
python eval/scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir eval/evaluation/outputs/eval ^
  --enable-ragas ^
  --require-ragas ^
  --experiment-name "final_submission_eval"
```

### bash 예시

```bash
python eval/scripts/run_evaluation.py \
  --eval-dir data/eval \
  --predictions outputs/predictions.jsonl \
  --output-dir eval/evaluation/outputs/eval \
  --enable-ragas \
  --experiment-name "baseline_with_ragas"
```

## 8. 출력 파일 설명

run별 출력 파일은 기본적으로 `eval/evaluation/outputs/eval/` 아래에 저장된다.

- `eval_results.csv`: 문항별 Phase 1 검색 성능 결과
- `eval_results.json`: 문항별 Phase 1 결과의 JSON 버전
- `eval_summary.md`: 전체 평가 요약
- `eval_by_type.csv`: type별 평균 결과
- `eval_by_difficulty.csv`: difficulty별 평균 결과
- `failure_cases.csv`: 실패 케이스 목록
- `ragas_results.csv`: RAGAS 문항별 결과 또는 오류 정보
- `ragas_summary.md`: RAGAS 요약

실험 누적 로그는 `eval/evaluation/outputs/eval/experiment_logs/` 아래에 저장된다.

- `phase1_retrieval_experiments.csv`
- `phase2_ragas_experiments.csv`
- `failure_analysis_experiments.csv`

experiment log는 append-only다. 기존 로그를 덮어쓰지 않고 새 실험 행을 뒤에 추가한다.

## 9. 모듈별 역할

- `config.py`: 공식 top_k, metric 이름, 기본 경로, 로그 파일명 등 상수 관리
- `schemas.py`: 평가 데이터 구조 설명용 dataclass 관리
- `loaders.py`: eval CSV와 predictions JSONL 로딩
- `normalization.py`: 구조화 필드 파싱, 문서명 정규화, top-5 unique documents 생성
- `retrieval_metrics.py`: `hit_at_5`, `mrr_at_5`, `ndcg_at_5` 계산
- `ragas_evaluator.py`: RAGAS import, Dataset 변환, `evaluate()` 호출, 오류 기록
- `aggregation.py`: overall/type/difficulty 평균과 실패 케이스 구성
- `reports.py`: run별 CSV/JSON/Markdown 리포트 저장
- `experiment_logger.py`: append-only experiment log 저장
- `path_utils.py`: 프로젝트 루트 기준 경로 처리와 JSON 저장 보조 함수
- `runner.py`: CLI 인자 처리와 전체 실행 흐름 관리

## 10. 테스트 방법

프로젝트 루트에서 다음 명령을 실행한다.

```powershell
python -m pytest evaluation/tests -q
```

테스트는 다음을 검증한다.

- predictions JSONL 로딩
- `ground_truth_docs` 파싱
- 문서명 정규화와 filename 우선 정책
- rank 정렬 후 top-5 unique documents 생성
- `hit_at_5`, `mrr_at_5`, `ndcg_at_5` 계산
- 빈 `ground_truth_docs` NaN 처리
- experiment log append-only 동작
- RAGAS 기본 evaluator 호출 방식
- RAGAS 실패 시 strict mode exit code와 Phase 1 결과 저장

## 11. RAGAS 사용 시 주의사항

- `ragas==0.1.21`로 고정되어 있다.
- `datasets` 등 dependency 설치가 필요하다.
- RAGAS 기본 evaluator가 요구하는 API key 또는 환경 변수가 필요할 수 있다.
- API key 값은 로그, 리포트, README에 저장하지 않는다.
- RAGAS가 실패해도 Phase 1만으로 검색 성능 실험을 계속할 수 있다.
- 최종 제출용 평가는 `--enable-ragas --require-ragas`를 사용한다.

## 12. 실험 로그 작성 방식

실험할 때마다 새 파일을 만드는 대신 누적 CSV에 append한다.

공통으로 기록하는 값은 다음이다.

- `experiment_id`
- `experiment_name`
- `run_datetime`
- `notes`

실험 로그는 성능 변화 추적과 보고서 작성 근거로 사용한다. 예를 들어 chunk size, retriever type, reranker 여부가 바뀌었을 때 검색 성능이 어떻게 달라졌는지 비교할 수 있다.

## 13. 보안 및 데이터 주의사항

- 원본 RFP 본문을 README, 로그, 리포트에 길게 저장하지 않는다.
- API key, SSH key, 개인 정보는 저장하지 않는다.
- GitHub에 원본 데이터가 올라가지 않도록 주의한다.
- predictions JSONL의 `retrieved_contexts.text`에는 평가에 필요한 짧은 context만 포함하고, 리포트에는 원문 context를 길게 저장하지 않는다.

## 14. 자주 생기는 문제

### ModuleNotFoundError: rag_eval

`eval/scripts/run_evaluation.py` 또는 `eval/evaluation/scripts/run_evaluation.py`로 실행해야 한다. 이 entrypoint가 `eval/evaluation/src`를 import path에 추가한다. 테스트는 `eval/evaluation/tests/conftest.py`가 같은 역할을 한다.

### RAGAS import error

`evaluation/requirements.txt` 기준으로 dependency를 설치한다.

```powershell
pip install -r evaluation/requirements.txt
```

### datasets 미설치

RAGAS Dataset 변환에 `datasets`가 필요하다. `evaluation/requirements.txt`에 포함되어 있다.

### API key 없음

RAGAS 기본 evaluator가 API key 또는 환경 변수를 요구할 수 있다. 팀 공통 설정을 사용하되, key 값을 코드나 로그에 저장하지 않는다.

### Windows 한글 경로 문제

경로는 `pathlib.Path`로 처리한다. PowerShell에서 경로를 따옴표로 감싸면 공백/한글 경로 문제를 줄일 수 있다.

### pytest-current PermissionError atexit 메시지

Windows에서 pytest 임시 symlink 정리 중 `PermissionError`가 atexit에 출력될 수 있다. 테스트 결과가 `passed`이고 exit code가 0이면 테스트 실패는 아니다.

### predictions id와 eval id가 매칭되지 않음

`predictions.jsonl`의 `id`가 eval CSV의 `id`와 같아야 한다. 매칭되지 않으면 해당 문항은 prediction missing으로 처리될 수 있다.

### ground_truth_docs 파싱 실패

`ground_truth_docs`는 JSON list 문자열을 권장한다.

```json
["샘플문서.hwp"]
```

문자열 형식이 깨지면 빈 list로 파싱될 수 있고, 이 경우 Phase 1 metric은 NaN 처리된다.
