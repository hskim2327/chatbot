# 서비스 실행 가이드

로컬에서 RFP 챗봇 형태로 실행하는 방법입니다.

## 필요 파일

로컬 실행에는 대용량 데이터와 index가 필요합니다.

```text
data/processed/chunks_v2_690.jsonl
data/processed/source_store_v2_690.jsonl
indexes/chroma_kure_v1_chunks_v2_690/
```

위 파일들은 Git에 올리지 않습니다.

## 실행

```bash
.venv/bin/python scripts/rag_service_web.py   --host 127.0.0.1   --port 7860   --use-best-adapter
```

브라우저에서 접속합니다.

```text
http://127.0.0.1:7860
```

## UI 동작

- Enter: 전송
- Shift+Enter: 줄바꿈
- 새 대화: history 초기화
- 첫 응답에는 모델 로딩 시간이 오래 걸릴 수 있음

## History 처리

후속 질문에서 이전 대화 전체를 검색어로 그대로 쓰지 않습니다.

대신 다음 정보만 상태로 유지합니다.

- 최근 문서/사업명
- 최근 기관명
- 최근 금액
- 최근 답변 대상

이렇게 해야 “그거 어디에 쓰기로 했어?” 같은 후속 질문에서 이전 답변 문장이 검색어에 섞이는 문제를 줄일 수 있습니다.

## 주의

현재 서비스는 데모용입니다. 답변은 간결하게 보여주지만, 내부적으로는 retrieval, context 구성, generation, 후처리 과정을 거칩니다.

실무 사용 전에는 근거 문서 표시, citation validation, 금액/날짜 검증을 더 강화하는 것이 좋습니다.
