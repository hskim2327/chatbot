# 단일 파일 RAG 평가 스크립트 계획서

## 1. 프로젝트 평가 목적

시나리오 A, 즉 GCP/HuggingFace 기반 로컬 RAG 시스템을 대상으로 RFP 질의응답 성능을 평가한다. 평가는 정답 문서 검색 성능, RAGAS 기반 생성 품질, 실패 원인 분석, 실험별 성능 변화 추적을 포함한다.

## 2. 참고한 가이드/노트북 파일

- `AI_중급_프로젝트_가이드.pdf`: RFP 기반 RAG 시스템 목표, 평가 기준, 제출물, 보안 및 원본 데이터 외부 공유 금지 확인.
- `rag_pipeline_road_map.ipynb`: 파싱, 청킹, 임베딩, Vector DB, hybrid search, reranking 흐름 확인.
- `3_RAG_평가지표_및_해석하기.ipynb`: Hit Rate, MRR, nDCG, RAGAS 기반 Faithfulness, Answer Relevancy, Context Precision, Context Recall 확인.

## 3. 데이터 파일 구조 요약

- `data/data_list_advanced.xlsx`: 690행 x 12열, 텍스트 결측 0건.
- `data/data_list_reparsed.xlsx`: 98행 x 12열, 텍스트 결측 77건.
- `data/eval/*.csv`: 총 38개, 전체 1,100행, 고유 id 500개. 중복/확장 batch가 포함되어 있다.

## 4. advanced/reparsed 데이터 비교

`advanced`는 파일명 690개, 사업명 682개, 발주 기관 406개, hwp 665건/pdf 25건이며 baseline corpus로 적합하다.

`reparsed`는 텍스트 결측이 많아 baseline corpus로 부적합하고, 보조 분석 또는 파싱 개선 실험용으로 둔다.

## 5. eval CSV 구조 분석

canonical 평가셋은 `eval_batch_01.csv`부터 `eval_batch_25.csv`까지의 500문항으로 잡는다.

canonical 기준:

- type: A 150, B 200, C 50, D 50, E 50
- difficulty: 하 254, 중 155, 상 91
- 단일 정답 문서 질문: 297개
- 다중 정답 문서 질문: 203개
- history 필요 질문: 50개
- type D: 문서에 없는 질문
- type E: 오타/구어체/비표준 표현 견고성 질문

## 6. eval과 corpus 매칭 결과

canonical ground truth 고유 문서 수는 41개다.

- advanced: 40개 exact match, 텍스트 비어 있는 문서 0개
- reparsed: 40개 exact match, 텍스트 비어 있는 문서 34개
- exact match 실패: `인천공항운영서비스(주)_인천공항운서비스㈜ 차세대 ERP시스템 구축 .hwp`

채점은 exact match 기반으로 하되, 파일명 표기 차이는 failure analysis에 남긴다.

## 7. baseline corpus 추천

baseline corpus는 `data/data_list_advanced.xlsx`를 사용한다. `reparsed`는 결측 때문에 retrieval 실패와 데이터 품질 실패를 구분하기 어렵다.

## 8. 단일 파일 평가 스크립트 채택 이유

최종 구현은 `scripts/run_evaluation.py` 단일 파일로 한다. 여러 `.py` 모듈로 분리하지 않고, 섹션 주석과 함수 단위로 논리적 모듈화를 한다.

## 9. 전체 평가 아키텍처

입력은 eval CSV directory와 predictions JSONL이다. 처리 흐름은 eval 로드, prediction 로드, 문서명 정규화, Phase 1 metric 계산, Phase 2 RAGAS 평가, Phase 3 failure 분석, run별 리포트 저장, experiment log append 순서다.

## 10. Phase 1: Deterministic Retrieval Evaluation

Phase 1은 OpenAI API와 RAGAS 없이 실행한다. 목적은 검색기가 정답 문서를 top-5 안에 가져오는지 재현 가능하게 평가하는 것이다.

공식 평가는 `top_k=5` 기준으로 고정한다. 공식 컬럼명은 반드시 다음으로 고정한다.

- `hit_at_5`
- `mrr_at_5`
- `ndcg_at_5`

평가 대상 검색 결과는 `retrieved_contexts`를 `rank` 오름차순으로 정렬한 뒤, 문서 기준으로 중복 제거한 top-5 unique documents다.

문서 식별 우선순위:

1. `filename`
2. `doc_id`

`retrieved_contexts`에 `filename`과 `doc_id`가 모두 있으면 `filename`을 우선 채점 기준으로 사용한다.

## 11. Phase 1 지표 정의

### Hit@5

top-5 unique documents 안에 `ground_truth_docs` 중 하나 이상이 있으면 1, 없으면 0이다. 다중 정답 문서 질문에서도 하나 이상 맞으면 hit로 본다.

### MRR@5

top-5 unique documents 안에서 가장 먼저 등장한 정답 문서의 reciprocal rank를 계산한다. 정답이 없으면 0이다.

### nDCG@5

정답 문서는 relevance 1, 비정답 문서는 0으로 두고 DCG@5 / IDCG@5를 계산한다. 다중 정답 문서가 상위에 여러 개 배치될수록 높아진다.

### 빈 ground_truth_docs 처리

`ground_truth_docs`가 비어 있는 문항은 Phase 1 retrieval metric 계산에서 제외한다. `hit_at_5`, `mrr_at_5`, `ndcg_at_5`는 NaN으로 기록하고 평균 계산 denominator에서도 제외한다.

## 12. Phase 1 type별/difficulty별 분석 방식

집계는 다음 기준으로 수행한다.

- overall Hit@5 / MRR@5 / nDCG@5
- by type Hit@5 / MRR@5 / nDCG@5
- by difficulty Hit@5 / MRR@5 / nDCG@5

type과 difficulty는 metric이 아니라 grouping 기준이다.

## 13. Phase 2: RAGAS-based Generation Evaluation

Phase 2는 RAGAS 기반 생성 품질 평가다. 최종 제출용 평가에서는 반드시 실행한다.

RAGAS 라이브러리와 RAGAS 기본 evaluator 설정을 고정한다. custom llm, custom embeddings, 별도 judge backend adapter는 사용하지 않는다.

## 14. RAGAS 버전 및 기본 evaluator 정책

RAGAS 버전은 `requirements.txt`에 `ragas==0.1.21`로 고정한다. 해당 버전의 공식 문서 기준으로 다음 import와 호출 방식을 사용한다.

```python
from ragas import evaluate
from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
```

`evaluate()`에 custom llm 또는 custom embeddings를 주입하지 않는다. RAGAS 기본 evaluator가 요구하는 API key와 환경 변수는 모든 팀이 동일하게 설정해야 한다.

기본 입력 schema는 강의 예시와 동일하게 다음 컬럼을 우선 사용한다.

- `question`
- `answer`
- `contexts`
- `ground_truth`

필요 시 RAGAS 버전에 맞춰 `column_map`을 사용할 수 있으나, 현재 구현의 기본값은 column map을 사용하지 않는다.

## 15. RAGAS 지표 정의

Phase 2 필수 지표:

- Faithfulness
- Answer Relevancy
- Context Precision
- Context Recall

RAGAS 실행 전체가 실패하거나 문항별 오류가 발생하면 `ragas_error`에 기록한다. 일부 문항만 성공한 경우에도 가능한 결과 파일은 저장한다.

## 16. Phase 3: Failure Case Analysis

Phase 1과 Phase 2 결과를 결합해 실패 원인을 분류한다.

후보:

- 검색 실패
- 정답 문서 top-5 밖
- context 부족
- hallucination
- faithfulness 낮음
- answer relevancy 낮음
- type C follow-up 맥락 실패
- type E 견고성 실패
- 파일명 매칭 실패
- 파싱 데이터 품질 문제
- RAGAS 실행 오류

## 17. eval input schema

필수 필드:

- `id`
- `type`
- `difficulty`
- `question`
- `ground_truth_answer`
- `ground_truth_docs`
- `metadata_filter`
- `history`

파생 필드:

- `ground_truth_doc_list`
- `has_history`
- `is_multi_doc`
- `is_unanswerable`
- `normalized_type`
- `normalized_difficulty`

## 18. predictions JSONL schema

필수 필드:

- `id`
- `question`
- `answer`
- `retrieved_contexts`
- `latency_ms`
- `model_name`
- `embedding_model`
- `retriever_config`

`retrieved_contexts` 항목:

- `rank`
- `filename` 또는 `doc_id`
- `chunk_id` optional
- `score`
- `text`
- `metadata`

`filename`과 `doc_id`가 모두 있으면 `filename`을 우선 사용한다.

## 19. output report schema

run별 출력 파일:

- `outputs/eval/eval_results.csv`
- `outputs/eval/eval_results.json`
- `outputs/eval/eval_summary.md`
- `outputs/eval/eval_by_type.csv`
- `outputs/eval/eval_by_difficulty.csv`
- `outputs/eval/failure_cases.csv`
- `outputs/eval/ragas_results.csv`
- `outputs/eval/ragas_summary.md`

Phase 1 컬럼:

- `id`, `type`, `difficulty`
- `hit_at_5`, `mrr_at_5`, `ndcg_at_5`
- `first_relevant_rank`
- `retrieved_doc_ids`
- `ground_truth_docs`

Phase 2 컬럼:

- `id`
- `faithfulness`
- `answer_relevancy`
- `context_precision`
- `context_recall`
- `ragas_error`

## 20. Experiment Log CSV Append Strategy

평가 실행 결과는 단발성 리포트로만 저장하지 않고, 실험 단위 누적 CSV에도 append한다.

각 실험은 다음 공통 식별자를 가진다.

- `experiment_id`
- `experiment_name`
- `run_datetime`
- `notes`

누적 로그는 append-only로 관리한다. 파일이 없으면 header와 함께 새로 생성하고, 파일이 있으면 기존 내용을 덮어쓰지 않고 행만 추가한다.

누적 로그 파일:

- `outputs/eval/experiment_logs/phase1_retrieval_experiments.csv`
- `outputs/eval/experiment_logs/phase2_ragas_experiments.csv`
- `outputs/eval/experiment_logs/failure_analysis_experiments.csv`

`phase2_ragas_experiments.csv`에는 다음 재현성 정보를 반드시 기록한다.

- `ragas_version`
- `ragas_metrics`
- `ragas_input_schema`
- `ragas_column_map`
- `ragas_default_evaluator_used`
- `python_version`
- `platform`
- `run_environment`
- `ragas_error_count`

`ragas_default_evaluator_used`는 항상 `true`로 기록한다.

## 21. scripts/run_evaluation.py 내부 섹션 구조

단일 파일 내부 구조:

1. Imports & Constants
2. Data Schemas
3. Path Utilities
4. Loaders
5. Normalization
6. Retrieval Metrics
7. RAGAS Evaluation Interface
8. Aggregation
9. Report Writers
10. CLI / Main

`Report Writers`는 run별 리포트 저장과 experiment log append를 모두 담당한다.

## 22. CLI 설계

기본 옵션:

- `--eval-dir`
- `--predictions`
- `--output-dir`
- `--canonical-only`
- `--top-k`
- `--experiment-id`
- `--experiment-name`
- `--notes`

RAGAS 옵션:

- `--enable-ragas`
- `--ragas-sample-size`
- `--ragas-output-path`

사용하지 않는 옵션:

- `--judge-model`
- `--embedding-model-for-ragas`

공식 평가에서는 `--top-k 5`를 사용한다. 내부적으로도 공식 metric 컬럼명은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`로 고정한다.

## 23. 구현 우선순위

1. `docs/evaluation_plan.md` 작성
2. `scripts/run_evaluation.py` 단일 파일 골격 작성
3. eval/prediction loader 작성
4. rank 정렬 및 filename 우선 문서 식별 로직 작성
5. filename/doc_id 기준 unique top-5 추출
6. 문서명 정규화
7. Hit@5, MRR@5, nDCG@5 계산
8. 빈 ground_truth_docs NaN 처리
9. overall/type/difficulty 집계
10. Phase 1 run별 리포트 저장
11. Phase 1 experiment log append
12. RAGAS interface 작성
13. RAGAS 오류를 `ragas_error`에 기록하고 가능한 결과 저장
14. RAGAS 결과 저장 및 Phase 2 experiment log append
15. failure case 분석 및 failure experiment log append

## 24. 제외하거나 Future Work로 둘 항목

1차 필수 범위 제외:

- Hit@1
- Hit@3
- doc_recall@k
- metadata_filter_match
- chunk_hit@k
- chunk-level 평가
- fully manual grading
- RAGAS 없는 생성 품질 최종 판단

Future Work:

- chunk-level ground truth 확보 후 chunk metric
- metadata filter 정답 라벨 보강
- fuzzy matching을 채점에 반영할지 검토
- RAGAS 버전 업그레이드 시 metric import/schema 재검증

## 25. 리스크와 주의사항

- 원본 RFP 본문을 계획서나 리포트에 길게 복사하지 않는다.
- API Key, SSH Key, 개인 경로를 저장하지 않는다.
- Windows 한글 경로와 OneDrive 경로를 고려해 `argparse`와 `pathlib.Path`를 사용한다.
- 최종 코드는 절대경로 하드코딩에 의존하지 않는다.
- `reparsed`는 텍스트 결측이 많아 baseline으로 쓰지 않는다.
- 전체 38개 CSV를 무조건 합치면 중복/확장 batch 때문에 점수가 왜곡될 수 있다.
- experiment log는 append-only로 관리하며 기존 로그를 덮어쓰지 않는다.
- RAGAS가 일부 실패해도 가능한 결과는 반드시 저장한다.

## 26. 다음 Codex 작업 프롬프트 초안

`scripts/run_evaluation.py` 단일 파일 평가 스크립트를 개선하라. Phase 1은 rank 정렬 후 filename 우선, doc_id 보조 기준으로 unique top-5 documents를 만들고 Hit@5, MRR@5, nDCG@5만 계산한다. `ground_truth_docs`가 비어 있는 문항은 Phase 1 metric을 NaN으로 기록하고 평균에서 제외한다. Phase 2는 RAGAS v0.1.21 기본 evaluator로 `evaluate(dataset, metrics=[...])`를 호출하며 custom llm/custom embeddings는 주입하지 않는다. 각 실행은 `experiment_id`, `experiment_name`, `run_datetime`, `notes`를 가지고 Phase 1/RAGAS/failure analysis 결과를 `outputs/eval/experiment_logs/*.csv`에 append-only 방식으로 누적 기록한다.
