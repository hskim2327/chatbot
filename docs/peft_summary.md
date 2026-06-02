# PEFT 실험 요약

## 목적

Qwen 모델이 RFP 문서 기반 질의응답 형식에 더 잘 맞도록 PEFT를 시도했습니다.

목표는 문서 지식을 모델에 외우게 하는 것이 아니라, 다음 답변 습관을 학습시키는 것이었습니다.

- 제공된 context 안에서만 답하기
- 금액/날짜/기관명은 원문 표현을 유지하기
- 여러 문서 질문은 문서별로 나눠 답하기
- 근거가 없으면 확인 불가라고 답하기
- 근거 문서와 근거 문장을 함께 제시하기

## 사용 모델

```text
unsloth/Qwen3-8B-bnb-4bit
```

LoRA/QLoRA 방식으로 adapter를 학습했습니다.

## 데이터 구성

PEFT 학습에는 원문 문서 전체가 아니라 다음 형태의 라벨이 필요했습니다.

```text
question + context -> answer
```

즉, RAG 시스템에서 실제로 모델에게 줄 context를 넣고, 그 context를 보고 어떤 답변을 해야 하는지 학습시키는 방식입니다.

## 라벨 생성

라벨은 GPT를 이용해 초안을 만들고, `trainable=true/false` 기준으로 검수했습니다.

문제가 된 부분:

- 답변불가 라벨이 많음
- source_store와 retrieved context가 충돌하는 샘플 존재
- 일부 문항은 정답 근거가 context에 부족함
- 유형별 균형이 충분하지 않음

## 결과 해석

PEFT 파이프라인은 동작했고 adapter도 만들었습니다. 다만 라벨 수가 적어서 실제 생성 성능을 안정적으로 끌어올리기에는 부족했습니다.

현재 결론은 다음과 같습니다.

- PEFT는 가능하다.
- 하지만 지금 단계에서는 retrieval/context 개선 효과가 더 컸다.
- PEFT를 계속하려면 정답형 고품질 라벨을 더 확보해야 한다.

## 다음 단계

- 정답형 라벨 50~100개 추가 확보
- 답변불가 라벨 비중 조절
- 예산/금액, required fields, multi-doc 유형별 균형 맞추기
- source_store와 retrieved context 충돌 샘플 제외 또는 별도 처리
- 기존 best adapter를 기준으로 재학습
