# Phase 4 LLM Judge 문서 안내

이 파일은 기존 테스트와 문서 참조 호환성을 위한 안내 문서다.

최신 Phase 4 설계와 실행 절차는 아래 문서를 기준으로 확인한다.

- `eval/evaluation/docs/archive/phase4_llm_judge_implementation_plan.md`: Phase 4 LLM Judge 구현 계획
- `eval/evaluation/docs/phase4_llm_judge_api_runbook.md`: Phase 4 API mode 실행 가이드
- `EVALUATION_GUIDE.md`: 전체 평가 모듈 사용 가이드

현재 Phase 4는 `evidence_only` 기본 reference mode를 사용하며, `mock`, `dry_run`, `api` mode를 지원한다. 실제 API 실행 전에는 반드시 `dry_run`과 작은 `sample-size`로 입력과 결과 파일을 확인한다.
