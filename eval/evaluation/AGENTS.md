# AGENTS.md

## 목적

이 문서는 `evaluation/` 폴더의 RAG 평가 모듈을 Codex가 작업할 때 따라야 할 전용 지침이다. 프로젝트 루트의 `AGENTS.md` 공통 지침도 함께 따른다.

## 평가 정책 고정 지침

- 평가 정책을 임의로 변경하지 않는다.
- Phase 1 metric은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`만 사용한다.
- 공식 `top_k`는 5다.
- `retrieved_contexts`는 `rank` 오름차순으로 정렬한다.
- 문서 식별은 `filename`을 우선 사용하고, `filename`이 없을 때만 `doc_id`를 사용한다.
- 같은 문서가 여러 chunk로 검색되면 중복 제거하여 top-5 unique documents를 만든다.
- `ground_truth_docs`가 비어 있으면 Phase 1 metric은 NaN으로 기록한다.
- NaN 문항은 평균 denominator에서 제외한다.
- `doc_recall@k`, `hit@1`, `hit@3`, `chunk_hit@k`를 임의로 추가하지 않는다.

## Phase 1 작업 규칙

- Phase 1은 document-level retrieval evaluation이다.
- chunk-level ground truth가 없는 상태에서 chunk-level metric을 필수 지표로 만들지 않는다.
- Phase 1 결과 파일과 Phase 1 experiment log는 RAGAS 성공/실패와 무관하게 저장되어야 한다.

## Phase 2 RAGAS 작업 규칙

- Phase 2는 RAGAS 라이브러리를 고정 사용한다.
- RAGAS 호출 방식은 `evaluate(dataset, metrics=[...])` 기본 evaluator 방식을 유지한다.
- custom llm, custom embeddings, judge backend adapter를 만들지 않는다.
- RAGAS metric은 `faithfulness`, `answer_relevancy` 또는 `response_relevancy`, `context_precision`, `context_recall` 정책을 따른다.
- `ragas==0.1.21` 고정 정책을 임의로 바꾸지 않는다.
- RAGAS 오류는 `ragas_error`에 기록한다.
- RAGAS 실패가 Phase 1 결과 저장을 방해하면 안 된다.

## 실행 플래그 정책

- 기본 실행은 Phase 1만 수행한다.
- `--enable-ragas`가 있을 때만 Phase 2를 수행한다.
- `--require-ragas`는 최종 제출용 strict mode다.
- `--require-ragas`는 `--enable-ragas`와 함께 사용해야 한다.
- `--require-ragas`가 없으면 RAGAS 실패는 전체 프로그램 실패로 처리하지 않는다.
- `--require-ragas`가 있으면 가능한 결과 파일을 저장한 뒤 non-zero exit code로 종료한다.

## Experiment log 정책

- experiment logs는 append-only다.
- 기존 experiment log 파일을 덮어쓰지 않는다.
- 모든 실험 로그에는 `experiment_id`, `experiment_name`, `run_datetime`, `notes`를 포함한다.
- API key 값, SSH key 값, 개인 정보, 원본 RFP 본문은 로그에 저장하지 않는다.
- 기본 로그 위치는 `evaluation/outputs/eval/experiment_logs/`다.

## 테스트 정책

- 테스트는 `python -m pytest evaluation/tests -q`로 실행한다.
- 평가 정책을 바꾸지 않는 리팩토링도 테스트를 실행해 기존 동작이 유지되는지 확인한다.
- 필수 검증 범위는 다음이다.
  - predictions JSONL 로딩
  - `ground_truth_docs` 파싱
  - 문서명 정규화
  - top-5 unique documents 생성
  - `hit_at_5`, `mrr_at_5`, `ndcg_at_5` 계산
  - 빈 `ground_truth_docs` NaN 처리
  - experiment log append-only 동작
  - RAGAS 실패 시 `ragas_error` 기록
  - `--enable-ragas`와 `--require-ragas` 실행 정책

## 주석과 문서화 규칙

- 주석과 docstring은 한국어로 작성한다.
- README와 Markdown 문서는 한국어로 작성한다.
- 변수명, 함수명, metric 컬럼명은 Python 관례에 맞게 영어 snake_case를 유지한다.
- 팀원이 코드 리뷰할 때 왜 해당 함수가 필요한지 이해할 수 있도록 설명한다.

## 보안 및 데이터 주의사항

- 원본 RFP 본문을 README, 로그, 리포트에 길게 저장하지 않는다.
- API key, SSH key, 개인 정보를 저장하지 않는다.
- GitHub에 원본 데이터가 올라가지 않도록 주의한다.
- 테스트 예시에는 짧은 더미 텍스트만 사용한다.
