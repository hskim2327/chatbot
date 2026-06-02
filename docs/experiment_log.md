# 실험 로그 요약

이 문서는 주요 실험 흐름만 간단히 정리합니다. 상세 로컬 로그는 `notebooks/rag_experiment_log.md`와 `outputs/reports/` 아래에 남아 있습니다.

## 1. Retrieval 실험

처음에는 FAISS/OpenAI embedding 기반으로 시작했지만, 최종적으로는 KURE embedding + Chroma 기반 검색을 사용했습니다.

시도한 기법:

- dense retrieval
- hybrid retrieval
- keyword rerank
- query decomposition
- RRF merge
- document-level scoring
- target-aware retrieval
- metadata/entity match score
- document diversity control

결과적으로 복잡한 hybrid/rerank보다 KURE dense retrieval에 query decomposition, document scoring, target-aware 보정을 붙인 방식이 안정적이었습니다.

## 2. Evidence 실험

정답 문서가 검색돼도 정답 근거 chunk가 context에 들어오지 않는 문제가 있었습니다.

이를 확인하기 위해 evidence recall 진단을 따로 만들었습니다.

시도한 기법:

- source_store final 값 활용
- fact_type 기반 evidence 선택
- 문서별 required evidence 최소 보장
- raw top 문서 보존
- 선택적 top 문서 보존
- source_store 값 검증 guard

결론적으로 raw top 문서를 전부 넣는 방식은 context coverage는 좋아졌지만 noisy해질 수 있었습니다. 최종적으로는 target 문서와 질문 유형에 맞는 evidence를 우선 넣는 방식이 더 안정적이었습니다.

## 3. Generation 실험

Qwen3 8B 4bit를 사용해 생성 결과를 확인했습니다.

시도한 기법:

- current context baseline
- source_store 추가
- context pruning
- RFP 전용 prompt
- 질문 유형별 답변 템플릿
- 금액 정규화
- 숫자/날짜 warning
- 후속 질문 history 처리

가장 효과가 컸던 부분은 모델 교체보다 context 구성 방식이었습니다. 특히 예산 질문에는 금액/단위/환산값을, 제출서류/자격요건 질문에는 원문 항목을 우선 넣도록 바꾼 것이 도움이 됐습니다.

## 4. PEFT 실험

PEFT는 Qwen이 RFP 답변 형식에 익숙해지도록 하기 위해 시도했습니다.

진행 흐름:

1. 질문/context/source_store/gold를 묶은 labeling bundle 생성
2. GPT로 답변 라벨 생성
3. trainable 라벨 검수
4. SFT 포맷 변환
5. LoRA/QLoRA 학습
6. base vs adapter 비교

PEFT는 validation loss 개선은 있었지만, 라벨 수가 적어 실제 생성 품질 안정화에는 한계가 있었습니다.

## 5. 서비스 실험

실험 결과를 실제로 체감하기 위해 웹 챗봇 서비스를 만들었습니다.

개선한 UX:

- 질문/답변 중심 UI
- Enter 전송
- Shift+Enter 줄바꿈
- 첫 응답 로딩 안내
- 생성 중 표시
- history 기반 후속 질문 처리
- 불필요한 근거/메타데이터 숨김

## 결론

가장 중요한 개선 포인트는 retrieval 자체보다 evidence selection과 context 구성입니다. PEFT와 모델 교체는 보조 수단이고, 현재 시스템에서는 “정확한 근거를 LLM 앞에 놓는 것”이 더 큰 영향을 줬습니다.
