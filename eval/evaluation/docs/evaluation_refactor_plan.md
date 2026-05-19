# RAG 평가 모듈 리팩토링 계획서

## 1. 현재 단일 파일 구조의 문제점

현재 `scripts/run_evaluation.py`는 약 639줄 규모의 단일 파일이다. 초기 구현 단계에서는 실행 흐름을 한 파일에서 확인할 수 있다는 장점이 있었지만, 팀 코드 리뷰와 유지보수 관점에서는 다음 문제가 있다.

- CLI, 데이터 로딩, 정규화, retrieval metric, RAGAS 실행, 집계, 리포트 저장, 실험 로그 저장이 한 파일에 함께 있다.
- 함수의 책임은 어느 정도 나뉘어 있지만, 파일 경계가 없어 변경 영향 범위를 파악하기 어렵다.
- RAGAS 실패 격리, experiment log append, Phase 1 metric 계산처럼 중요한 정책이 코드 곳곳에 흩어질 수 있다.
- 테스트가 `tests/test_run_evaluation.py` 하나에 모여 있어 어떤 테스트가 어떤 책임을 검증하는지 빠르게 파악하기 어렵다.
- 이후 팀원이 기능을 추가할 때 단일 파일에 계속 함수를 붙이게 되면, 평가 정책이 의도치 않게 바뀔 위험이 커진다.

이번 리팩토링의 목적은 평가 정책을 바꾸는 것이 아니라, 현재 동작을 유지한 채 코드 책임을 파일 단위로 나누는 것이다.

## 2. 제안 모듈 구조

리팩토링 후 구조는 다음을 기준으로 한다.

```text
scripts/
  run_evaluation.py

src/
  evaluation/
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
    runner.py

tests/
  evaluation/
    test_loaders.py
    test_normalization.py
    test_retrieval_metrics.py
    test_experiment_logger.py
    test_runner.py
```

`scripts/run_evaluation.py`는 CLI 진입점 역할만 한다. 실제 로직은 `src/evaluation/` 패키지 안으로 이동한다.

## 3. 각 모듈 책임

### scripts/run_evaluation.py

- CLI 실행 진입점이다.
- 내부 평가 로직을 직접 갖지 않는다.
- `rag_eval.runner`의 `main()`을 호출한다.
- 이 파일은 팀원이 실행 명령을 찾는 위치로만 유지한다.

### src/evaluation/config.py

- 공식 `top_k=5` 상수를 관리한다.
- metric 이름 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`를 관리한다.
- 기본 출력 경로를 관리한다.
- canonical batch 범위 `eval_batch_01.csv`부터 `eval_batch_25.csv`까지를 관리한다.
- experiment log 파일명을 관리한다.
- Phase 1 / Phase 2 실행 관련 기본 정책 상수를 관리한다.

### src/evaluation/schemas.py

- eval row 구조를 정의한다.
- prediction row 구조를 정의한다.
- retrieved context 구조를 정의한다.
- metric result 구조를 정의한다.
- 실험 로그 row 구조를 정의한다.
- RAGAS result 구조를 정의한다.
- `dataclass` 사용을 우선 검토한다. 다만 pandas DataFrame과 JSONL 변환이 중심이므로, 과도한 타입 계층을 만들지 않는다.

### src/evaluation/loaders.py

- eval CSV를 로딩한다.
- canonical eval set을 선택한다.
- predictions JSONL을 로딩한다.
- 필수 컬럼 누락, JSONL 파싱 실패, CSV 파일 누락 같은 형식 오류를 처리한다.
- 파일 경로는 `pathlib.Path`를 사용한다.

### src/evaluation/normalization.py

- `ground_truth_docs`를 list로 파싱한다.
- `metadata_filter`와 `history`를 dict/list로 파싱한다.
- 문서명을 Unicode NFC, 공백 정리 기준으로 정규화한다.
- retrieved context에서 `filename`을 우선 사용하고, 없을 때만 `doc_id`를 사용한다.
- `retrieved_contexts`를 `rank` 오름차순으로 정렬한 뒤 top-5 unique documents를 만든다.

### src/evaluation/retrieval_metrics.py

- `hit_at_5`를 계산한다.
- `mrr_at_5`를 계산한다.
- `ndcg_at_5`를 계산한다.
- `first_relevant_rank`를 계산한다.
- `ground_truth_docs`가 비어 있으면 Phase 1 metric을 NaN으로 반환한다.
- NaN 문항이 평균 denominator에 들어가지 않도록 계산 결과를 명확히 만든다.

### src/evaluation/ragas_evaluator.py

- RAGAS import를 담당한다.
- `ragas==0.1.21` 기준 metric import 경로를 사용한다.
- prediction/eval row를 RAGAS Dataset 입력으로 변환한다.
- `evaluate(dataset, metrics=[...])`를 호출한다.
- custom llm, custom embeddings, 별도 judge backend adapter를 만들지 않는다.
- RAGAS 오류를 `ragas_error`에 기록한다.
- 일부 문항만 실패하더라도 가능한 결과를 반환한다.
- RAGAS 실패가 Phase 1 결과 저장을 방해하지 않도록 오류를 이 모듈 안에서 격리한다.

### src/evaluation/aggregation.py

- overall 평균을 계산한다.
- type별 평균을 계산한다.
- difficulty별 평균을 계산한다.
- NaN 문항을 denominator에서 제외한다.
- Phase 1 결과와 Phase 2 결과를 id 기준으로 병합한다.
- failure analysis가 사용할 중간 요약 데이터를 만든다.

### src/evaluation/reports.py

- `eval_results.csv`를 저장한다.
- `eval_results.json`을 저장한다.
- `eval_summary.md`를 저장한다.
- `eval_by_type.csv`를 저장한다.
- `eval_by_difficulty.csv`를 저장한다.
- `failure_cases.csv`를 저장한다.
- `ragas_results.csv`를 저장한다.
- `ragas_summary.md`를 저장한다.
- RAGAS가 실패해도 Phase 1 결과와 가능한 RAGAS 오류 파일을 저장한다.

### src/evaluation/experiment_logger.py

- `phase1_retrieval_experiments.csv`에 append한다.
- `phase2_ragas_experiments.csv`에 append한다.
- `failure_analysis_experiments.csv`에 append한다.
- 파일이 없으면 header를 포함해 생성한다.
- 기존 파일은 덮어쓰지 않는다.
- `experiment_id`, `experiment_name`, `run_datetime`, `notes`를 모든 로그에 기록한다.
- Phase 1 로그는 RAGAS 성공/실패와 무관하게 반드시 append한다.

### src/evaluation/runner.py

- `argparse` 정의를 담당한다.
- 전체 실행 흐름을 관리한다.
- Phase 1을 실행한다.
- `--enable-ragas`가 있으면 Phase 2를 실행한다.
- `--require-ragas`가 있으면 RAGAS 실패를 strict mode로 처리한다.
- failure analysis를 실행한다.
- report writer를 호출한다.
- experiment logger를 호출한다.
- exit code 정책을 관리한다.

## 4. 실행 플래그와 실패 격리 정책

평가 스크립트는 Phase 1 검색 성능 평가와 Phase 2 RAGAS 평가를 플래그로 분리한다.

### 기본 실행 정책

기본 실행은 Phase 1 검색 성능 평가만 수행한다.

사용자가 `--enable-ragas`를 주지 않으면 다음만 실행한다.

- eval CSV 로드
- predictions JSONL 로드
- top-5 unique documents 생성
- `hit_at_5`, `mrr_at_5`, `ndcg_at_5` 계산
- overall/type/difficulty 집계
- Phase 1 run별 리포트 저장
- Phase 1 experiment log append
- failure analysis 중 Phase 1 기반 실패 분석 저장

### RAGAS 실행 정책

`--enable-ragas`가 주어진 경우에만 Phase 2 RAGAS evaluation을 추가로 수행한다.

RAGAS 실행 시 다음 정책을 유지한다.

- RAGAS 라이브러리를 고정 사용한다.
- `evaluate(dataset, metrics=[...])` 기본 evaluator 호출 방식을 사용한다.
- custom llm, custom embeddings, judge backend adapter는 만들지 않는다.
- RAGAS 오류는 `ragas_error`에 기록한다.
- 일부 문항만 성공해도 가능한 결과 파일은 저장한다.
- RAGAS 실패가 Phase 1 결과 저장을 막으면 안 된다.

### strict mode 정책

CLI에 `--require-ragas`를 추가한다.

`--require-ragas`는 최종 제출용 strict mode다.

정책:

- `--require-ragas`는 `--enable-ragas`와 함께 사용해야 한다.
- `--require-ragas`가 없으면 RAGAS 실패는 전체 프로그램 실패로 처리하지 않는다.
- `--require-ragas`가 없을 때 RAGAS가 실패하면 `ragas_error`에 기록하고 exit code 0을 유지한다.
- `--require-ragas`가 있으면 가능한 결과 파일을 저장한 뒤 non-zero exit code로 종료한다.
- 어떤 경우에도 Phase 1 결과 파일과 Phase 1 experiment log는 먼저 저장되어야 한다.

### 추천 실행 예시

검색 성능만 평가:

```powershell
python scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir outputs/eval ^
  --experiment-name "baseline_retrieval_only"
```

검색 성능 + RAGAS 평가:

```powershell
python scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir outputs/eval ^
  --enable-ragas ^
  --experiment-name "baseline_with_ragas"
```

최종 제출용 엄격 평가:

```powershell
python scripts/run_evaluation.py ^
  --eval-dir data/eval ^
  --predictions outputs/predictions.jsonl ^
  --output-dir outputs/eval ^
  --enable-ragas ^
  --require-ragas ^
  --experiment-name "final_submission_eval"
```

## 5. 한국어 주석/문서화 규칙

리팩토링 후 코드와 문서는 팀원이 빠르게 이해할 수 있도록 한국어 중심으로 작성한다.

- 파일 상단 주석은 한국어로 작성한다.
- 함수 docstring은 한국어로 작성한다.
- 복잡한 조건문에는 한국어 주석을 단다.
- 변수명과 함수명은 Python 관례에 맞게 영어 snake_case를 유지한다.
- metric 이름은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`처럼 영어로 유지한다.
- Markdown 문서는 한국어 제목과 설명을 사용한다.
- 팀원이 코드 리뷰할 때 왜 이 함수가 필요한지 바로 이해할 수 있게 작성한다.
- 단순한 대입문이나 자명한 로직에는 불필요한 주석을 달지 않는다.

## 6. 유지할 평가 정책

리팩토링 후에도 아래 정책은 절대 바꾸지 않는다.

- Phase 1 metric은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`만 사용한다.
- 공식 `top_k`는 5다.
- `retrieved_contexts`는 `rank` 오름차순 정렬 후 `filename` 우선, `doc_id` 보조 기준으로 top-5 unique documents를 만든다.
- `filename`과 `doc_id`가 둘 다 있으면 `filename`을 우선한다.
- `ground_truth_docs`가 비어 있으면 Phase 1 metric은 NaN으로 기록한다.
- NaN 문항은 평균 denominator에서 제외한다.
- Phase 2는 RAGAS 라이브러리를 고정 사용한다.
- RAGAS `evaluate()` 호출에는 custom llm/custom embeddings를 주입하지 않는다.
- RAGAS 오류는 `ragas_error`에 기록한다.
- 가능한 결과 파일은 저장한다.
- experiment logs는 append-only다.
- API key 값은 어떤 로그에도 저장하지 않는다.
- 원본 RFP 본문을 리포트나 로그에 길게 저장하지 않는다.
- 기본 실행은 Phase 1만 수행한다.
- `--enable-ragas`가 있을 때만 Phase 2를 수행한다.
- 최종 제출용 strict mode는 `--enable-ragas --require-ragas`로 실행한다.
- RAGAS 실패가 Phase 1 결과 저장을 방해하면 안 된다.

## 7. 테스트 계획

현재 `tests/test_run_evaluation.py`는 유지하되, 리팩토링 완료 시 `tests/evaluation/` 아래로 책임별로 나눈다.

권장 테스트 분리:

- `tests/evaluation/test_loaders.py`
- `tests/evaluation/test_normalization.py`
- `tests/evaluation/test_retrieval_metrics.py`
- `tests/evaluation/test_experiment_logger.py`
- `tests/evaluation/test_runner.py`

필수 테스트:

- eval CSV 로딩 테스트
- predictions JSONL 로딩 테스트
- `ground_truth_docs` 파싱 테스트
- 문서명 정규화 테스트
- top-5 unique documents 생성 테스트
- `hit_at_5` 계산 테스트
- `mrr_at_5` 계산 테스트
- `ndcg_at_5` 계산 테스트
- 빈 `ground_truth_docs` NaN 처리 테스트
- experiment log append 테스트
- RAGAS import 실패 시 `ragas_error` 기록 테스트
- RAGAS 실패 시에도 Phase 1 결과 파일 저장 테스트
- `--enable-ragas` 없이 Phase 1만 실행되는지 테스트
- `--enable-ragas`가 있을 때 Phase 2가 시도되는지 테스트
- `--require-ragas`가 없으면 RAGAS 실패에도 exit code 0인지 테스트
- `--require-ragas`가 있으면 RAGAS 실패 시 non-zero exit code인지 테스트
- CLI help 출력 테스트

기존 단일 테스트의 핵심 검증은 새 테스트로 모두 이전한 뒤, 중복이 사라지면 `tests/test_run_evaluation.py`는 제거하거나 smoke test만 남긴다.

## 8. 마이그레이션 순서

리팩토링은 기능 변경 없이 작은 단위로 진행한다.

1. `src/evaluation` 패키지를 생성한다.
2. `config.py`를 생성하고 상수만 이동한다.
3. `normalization.py`부터 분리한다.
4. `retrieval_metrics.py`를 분리한다.
5. `loaders.py`를 분리한다.
6. `reports.py`를 분리한다.
7. `experiment_logger.py`를 분리한다.
8. `ragas_evaluator.py`를 분리한다.
9. `aggregation.py`를 분리한다.
10. `runner.py`에서 전체 흐름을 연결한다.
11. `scripts/run_evaluation.py`를 얇은 entrypoint로 변경한다.
12. `tests/evaluation/`로 테스트를 분리한다.
13. `pytest` 전체를 실행한다.
14. Phase 1 smoke test를 실행한다.
15. `--enable-ragas` smoke test를 실행한다.
16. `--require-ragas` strict mode smoke test를 실행한다.

각 단계는 테스트가 통과한 뒤 다음 단계로 넘어간다.

## 9. 리스크와 대응

### import path 문제

리스크: `evaluation/scripts/run_evaluation.py`에서 `rag_eval.runner`를 찾지 못할 수 있다.

대응: 프로젝트 루트 기준 실행을 기본으로 하고, 필요하면 `pyproject.toml` 또는 테스트 설정에서 `pythonpath`를 명시한다. 임시로 `sys.path`를 조작하는 방식은 마지막 수단으로만 쓴다.

### Windows 한글 경로 문제

리스크: OneDrive, 한글 폴더명, 공백이 포함된 경로에서 파일 입출력이 깨질 수 있다.

대응: 모든 경로는 `pathlib.Path`로 처리하고, CSV/JSON/Markdown 저장 시 UTF-8 또는 UTF-8-SIG 인코딩을 명시한다.

### 기존 CLI 호환성 깨짐

리스크: 기존 사용자가 쓰던 `--eval-dir`, `--predictions`, `--output-dir`, `--canonical-only`, `--enable-ragas` 옵션이 깨질 수 있다.

대응: 기존 옵션은 유지하고, `--require-ragas`만 새로 추가한다. 옵션 이름을 바꾸지 않는다.

### RAGAS import 실패

리스크: `ragas` 또는 `datasets`가 설치되지 않은 환경에서 Phase 2가 실패할 수 있다.

대응: import 실패를 `ragas_error`에 기록한다. `--require-ragas`가 없으면 exit code 0을 유지하고, Phase 1 결과는 저장한다.

### RAGAS 실행 중 일부 문항 실패

리스크: 일부 문항의 context 형식, API 호출, evaluator 오류로 전체 RAGAS 평가가 중단될 수 있다.

대응: 가능한 범위에서 문항별 오류를 `ragas_error`에 기록한다. 전체 실패 시에도 오류 DataFrame을 만들어 `ragas_results.csv`를 저장한다.

### strict mode에서 결과 파일 저장 전 종료되는 문제

리스크: `--require-ragas` 실행 중 RAGAS 실패가 발생하면 결과 저장 전에 프로그램이 종료될 수 있다.

대응: runner는 Phase 1 리포트와 Phase 1 experiment log를 먼저 저장한다. RAGAS 결과와 오류도 가능한 만큼 저장한 뒤, 마지막에 exit code를 결정한다.

### experiment log schema 변경

리스크: append-only CSV의 컬럼이 실행마다 달라지면 누적 분석이 어려워진다.

대응: `config.py` 또는 `schemas.py`에 로그 컬럼 순서를 고정한다. 새 컬럼이 필요하면 문서와 테스트를 함께 수정한다.

### 기존 출력 파일 경로 변경

리스크: 리팩토링 중 output path가 바뀌면 기존 보고서 생성 흐름이 깨진다.

대응: `outputs/eval/` 아래 기존 파일명을 유지한다. 경로 상수는 `config.py`에서 관리한다.

### 테스트 파일 경로 변경

리스크: 테스트를 나누는 과정에서 기존 검증이 누락될 수 있다.

대응: 기존 `tests/test_run_evaluation.py`의 테스트 목록을 체크리스트로 삼아 새 테스트에 모두 이전한다. 이전이 끝난 뒤 전체 pytest를 실행한다.

### 팀원이 모듈 구조를 이해하지 못하는 문제

리스크: 파일은 나뉘었지만 책임 경계가 문서화되지 않으면 오히려 이해가 어려울 수 있다.

대응: 각 모듈 상단에 한국어 설명을 작성하고, 이 계획서의 “각 모듈 책임” 섹션을 README 또는 평가 문서에서 링크한다.

## 10. 리팩토링 완료 기준

다음 조건을 모두 만족하면 리팩토링을 완료한 것으로 본다.

- `scripts/run_evaluation.py`가 얇은 entrypoint가 된다.
- 핵심 로직이 `src/evaluation/` 아래 책임별 모듈로 이동한다.
- 기존 Phase 1 metric 결과가 리팩토링 전과 동일하다.
- RAGAS 기본 evaluator 정책이 유지된다.
- RAGAS 실패 시 Phase 1 결과 저장이 보장된다.
- experiment logs append-only 정책이 유지된다.
- `pytest` 전체가 통과한다.
- Phase 1 smoke test가 통과한다.
- `--enable-ragas` smoke test가 통과한다.
- `--require-ragas` strict mode smoke test가 의도한 exit code를 반환한다.

## 11. 다음 단계 제안

다음 Codex 작업에서는 이 계획서를 기준으로 실제 리팩토링을 수행한다. 구현 시에는 기능을 한 번에 옮기지 말고, `normalization.py`와 `retrieval_metrics.py`처럼 의존성이 낮은 모듈부터 분리한다. 각 모듈 분리 후 해당 테스트를 먼저 통과시키고, 마지막에 CLI smoke test로 전체 실행 흐름을 확인한다.
