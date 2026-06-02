# 최종 보고서

이 문서는 GitHub에서 바로 확인할 수 있도록 정리한 최종 보고서입니다.

상세 원본 보고서:

```text
outputs/reports/new_eval_rag_report_20260601.md
```

`outputs/`는 Git에 올라가지 않으므로, 핵심 내용만 이 문서에 요약합니다.

## 목표

RFP/입찰 문서 기반 질의응답 시스템을 만들고, 검색부터 생성, 평가, 서비스까지 end-to-end로 연결했습니다.

초기에는 정답 문서를 검색하는 데 집중했지만, 실험을 통해 더 중요한 병목이 드러났습니다.

> 정답 문서가 검색되더라도 실제 답변에 필요한 근거 chunk가 context에 들어오지 않으면 생성 모델은 정확히 답하기 어렵다.

그래서 최종 개선 방향은 다음 세 가지였습니다.

- 정답 문서 검색
- 정답 근거 evidence 확보
- 질문 유형별 context 구성

## 사용 데이터

- 최신 690 corpus 기반 chunk 데이터
- `source_store` 구조화 데이터
- Phase3/4 gold 50문항
- Qwen 기반 생성 결과

대용량 데이터와 실행 결과는 Git에 올리지 않고 로컬에서 관리했습니다.

## 최종 평가

팀 공통 최신 평가 모듈인 `eval`을 사용했습니다. 평가 로직은 수정하지 않고 그대로 실행했습니다.

| Phase | 지표 | 결과 |
|---|---|---:|
| Phase1 | hit@5 | 1.000 |
| Phase1 | MRR@5 | 0.920 |
| Phase1 | nDCG@5 | 0.911 |
| Phase2 RAGAS | faithfulness | 0.464 |
| Phase2 RAGAS | answer_relevancy | 0.141 |
| Phase3 | phase3_task_score | 0.541 |
| Phase3 | budget_numeric_accuracy | 0.229 |
| Phase4 | LLM Judge overall | 69.1점 |

## 주요 개선

### Retrieval

- KURE embedding + Chroma
- query decomposition
- RRF merge
- document scoring
- target-aware retrieval
- evidence recall 진단

### Context / Generation

- source_store/sidecar를 이용한 context 보강
- 질문 유형별 evidence selection
- 금액 정규화
- 예산/제출서류/자격요건/마감일 유형별 prompt/context 분기
- 짧은 답변 후처리

### PEFT

- GPT 기반 라벨 생성
- Qwen3 8B 4bit 대상 LoRA/QLoRA 실험
- base vs adapter 비교
- 라벨 수가 적어 최종 성능 향상은 제한적

### 서비스

- Gradio 기반 챗봇 UI
- Enter 전송, Shift+Enter 줄바꿈
- 첫 응답 로딩 안내
- 생성 중 표시
- history 기반 후속 질문 처리

## 결론

이번 프로젝트에서 가장 중요한 발견은 모델을 바꾸는 것보다 context 품질이 더 중요했다는 점입니다.

특히 정답 문서를 찾는 것과 정답 근거를 넣는 것은 다른 문제였습니다. 최종적으로는 retrieval, evidence selection, context 구성, generation 후처리, 평가, 서비스까지 연결된 1차 end-to-end 시스템을 완성했습니다.

남은 주요 개선 과제는 예산/금액 정확성, context precision, required field 계열 항목 추출입니다.
