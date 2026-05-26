# Context Engineering 개인 전략

## 한 줄 정의

나는 단순 전처리 담당이 아니라, **RFP 문서를 검색 가능한 구조로 바꾸고 그 전처리가 실제 retrieval 성능을 개선하는지 검증하는 담당**이다.

팀 내 공식 역할명은 다음처럼 잡는다.

> RFP 전처리 / 구조화 / 메타데이터 태깅 담당

외부적으로는 전처리 담당이지만, 실제 산출물은 retrieval 담당자가 바로 사용할 수 있는 고품질 인덱싱 입력까지 포함한다.

## 왜 이 역할이 중요한가

전처리는 결과를 보지 않으면 좋은지 나쁜지 판단할 수 없다.

RAG에서 좋은 전처리는 단순히 텍스트가 깨끗한 상태가 아니다. 좋은 전처리는 다음 조건을 만족해야 한다.

- 질문에 맞는 chunk가 더 잘 검색된다.
- `Hit Rate@5`, `MRR`, `Context Recall`이 오른다.
- LLM이 답변할 때 필요한 근거가 context 안에 들어온다.
- 날짜, 금액, 제출서류, 평가기준 같은 RFP 핵심 필드가 누락되지 않는다.
- 답변의 `Faithfulness`가 좋아진다.

따라서 전처리 담당자는 최소한 baseline retrieval 결과까지 확인해야 한다. 결과를 보지 않고 전처리 품질을 주장하는 것은 근거가 약하다.

## 팀 내 역할 경계

retrieval 담당자가 이미 있으므로, 역할 충돌을 피하기 위해 경계를 이렇게 둔다.

내 담당 범위:

- HWP/PDF 텍스트 품질 점검
- 노이즈 제거
- RFP 섹션 분리
- 표, 배점, 제출서류 구조화
- 날짜, 금액, 기관명, 공고번호 정규화
- chunk 생성
- chunk size 실험용 데이터셋 생성
- 자동 태그 생성
- Chroma에 넣을 metadata schema 정의
- retrieval 담당자에게 넘길 `chunks.jsonl` 또는 `chunks.parquet` 산출
- 전처리 산출물이 실제로 검색에 먹히는지 확인하기 위한 Chroma baseline 검색
- chunk/태그 전략별 `Hit@5`, `MRR`, `Context Recall` 비교

retrieval 담당자 주 담당 범위:

- Chroma 검색 쿼리 고도화
- dense search 전략
- BM25 sparse search
- RRF 결합
- rerank
- top-k 조정
- 최종 retrieval 파이프라인 통합
- generation 파이프라인과 연결

## 협업적으로 말하는 방식

팀에서 이렇게 말한다.

> 제가 전처리 산출물이 retrieval에 실제로 먹히는지 검증하려고, Chroma baseline 검색과 chunk/태그별 Hit@5 비교까지 같이 볼게요. 최종 retrieval 고도화는 retrieval 담당자와 맞춰서 넘기겠습니다.

이 표현의 장점:

- 남의 역할을 뺏는 느낌이 적다.
- 전처리 품질 검증이라는 명분이 명확하다.
- 내가 하고 싶은 retrieval modeling의 핵심을 자연스럽게 포함할 수 있다.
- 팀 전체 성능 개선에 직접 기여한다.

## 내가 끝까지 가져갈 핵심 산출물

### 1. RFP 구조화 전처리 산출물

- 문서별 clean text
- section path
- section type
- table markdown
- normalized date
- normalized amount
- issuer/project metadata
- requirement/evaluation/security tags

### 2. Chunk 데이터셋

chunk size별 산출물을 만든다.

- `small_256`: 날짜, 금액, 제출서류, 자격요건 검색용
- `medium_512`: 일반 QA 기본 검색용
- `large_1024`: 과업범위, 리스크, 요약용
- `table_summary`: 평가표, 배점표, 일정표, 제출서류 표 요약용

각 chunk에는 최소한 다음 metadata를 붙인다.

- `notice_id`
- `project_name`
- `issuer`
- `budget`
- `bid_deadline`
- `filename`
- `file_type`
- `section_path`
- `section_type`
- `chunk_size`
- `chunk_type`
- `tags`
- `has_table`
- `has_date`
- `has_amount`
- `has_requirement_keyword`

### 3. Baseline Retrieval 검증

내 전처리 산출물이 실제 검색에 도움이 되는지 확인하기 위해 최소 baseline은 직접 본다.

비교할 실험:

- clean 전/후
- context injection 전/후
- section tag 전/후
- chunk size 256 vs 512 vs 1024
- table summary 사용 전/후
- metadata filter 전/후

볼 지표:

- `Hit Rate@5`
- `MRR`
- `nDCG`
- `Context Recall`
- `retrieval_ms`

## 내가 보고서에서 어필할 포인트

보고서에서는 전처리를 감으로 했다고 쓰지 않는다. 반드시 지표와 연결한다.

좋은 표현:

- RFP 문서의 섹션 구조와 표 정보를 보존하기 위해 전처리 방식을 설계했다.
- 작은 chunk의 문맥 손실을 줄이기 위해 사업명, 발주기관, 섹션명을 context injection으로 추가했다.
- 평가기준, 제출서류, 입찰마감 같은 RFP 특화 섹션을 자동 태그로 분류했다.
- 전처리 전후 `Hit@5`, `MRR`, `Context Recall`을 비교하여 검색 성능 개선 여부를 검증했다.
- 전처리 결과가 generation의 `Faithfulness`에도 영향을 주는지 확인했다.

피해야 할 표현:

- 텍스트를 깨끗하게 만들었다.
- 적당히 chunk를 나눴다.
- 모델이 잘 찾도록 전처리했다.

## 판단 기준

내가 맡은 파트가 성공했다고 말하려면 다음을 보여줘야 한다.

- retrieval 담당자가 내 chunk와 metadata를 바로 사용할 수 있다.
- 전처리 전보다 검색 지표가 개선된다.
- 실패한 질문을 보고 어떤 전처리/태그/청킹 문제가 있었는지 설명할 수 있다.
- 속도와 정확도의 trade-off를 설명할 수 있다.
- 원본 RFP 데이터와 파생 전문을 GitHub에 올리지 않는다.

## 구조화 DB 고도화 방향

현재 기준은 `data_list_advanced.xlsx`와 원본 HWP/PDF 전체를 바탕으로 한 `advanced_690`이다. 다만 반복 실험 속도를 위해 처음부터 전체에 모든 고도화 전처리를 적용하지 않고, 평가 정답 문서를 포함한 pilot subset에서 추출/정제/태깅/청킹 품질을 먼저 검증한다.

DB 원천 산출물은 Excel이나 CSV가 아니라 JSONL로 둔다. chunk 1개를 JSON 1줄로 저장하고, `chunk_type`으로 일반 본문, 표, 이미지 OCR, 섹션 요약을 구분한다. Chroma에는 embedding 대상 `content`와 flat metadata만 넣고, 표 row dict와 OCR 원문 같은 중첩 구조는 JSONL 원본에 보존한다.

HWP 추출은 `pyhwpx`만 전제하지 않는다. `pyhwpx`는 한컴 정식 설치와 Windows COM 환경에 의존하므로 Viewer, Colab, GCP, headless 환경에서 실패할 수 있다. 따라서 `olefile` 기반 BodyText 직접 추출 코드를 fallback으로 유지하고, HWP 제어 정보가 한자처럼 보이는 artifact는 추출 직후 제거한다.

이전 기수의 6종 노이즈 정제 파이프라인은 추출 다음 단계에서 적용한다. 즉 `HWP/PDF 추출 -> artifact 제거 -> cleaner.py 정제 -> 섹션/표/OCR 구조화 -> JSONL 생성 -> Chroma 인덱싱` 순서로 진행한다.
## HWP 한자 예외 처리 원칙

- HWP artifact 제거 로직은 연속 한자 2글자 이상을 우선 검사한다.
- `甲`, `乙`, `內`, `有` 같은 단일 한자는 현재 정규식 단계에서 거의 제거 대상이 아니므로, 예외 목록은 단일 글자보다 의미 있는 표현 단위로 관리한다.
- 우선 보존 표현은 `甲乙`, `甲乙丙`, `甲乙丙丁`, `案內`, `內外`, `共有`, `未定`, `無償`, `有償`으로 둔다.
- 예외 목록은 raw-clean 비교에서 정상 표현이 실제로 제거되는 케이스가 확인될 때만 늘린다. 너무 넓히면 HWP 제어 정보 artifact가 살아남을 수 있다.
## 200개 pilot 한자 예외 후보 추출 계획

- 문서 1개 기준 한자 후보는 샘플 검증용으로만 사용한다.
- 보존/제거 예외는 최소 200개 pilot 문서에서 `count`, `doc_count`, `survives_clean_count`, `remove_artifact_count`, `artifact_context_count`를 집계한 뒤 결정한다.
- 실행 산출물은 하나의 CSV인 `outputs/hanja_exception_candidates.csv`로 둔다.
- 이 단계는 HWP OLE 파싱, zlib 압축 해제, UTF-16LE 디코딩, 정규식 집계 중심이므로 GPU를 쓰지 않는다. GPU는 KoE5 임베딩, reranker, LLM 태깅/요약, Vision OCR 단계에 사용한다.
- 예상 시간은 200개 기준 최소 5~10분, 중앙 15~30분, 최대 1시간 이상이다. 근거는 CPU/디스크 I/O 작업이며, 대용량 HWP나 손상 파일, 예외 로그가 많으면 늘어난다.
- 최종 `KEEP_HANJA_RUNS`는 CSV의 `keep_candidate`, `review_removed`, `review_artifact_context`를 사람이 검토한 뒤 반영한다.

## 핵심 실험 조건과 지표 확인

전처리 품질은 감으로 판단하지 않고, 같은 평가셋에서 retrieval 결과를 비교해 판단한다. 실험 조건은 너무 많이 벌리지 말고, 성능 차이를 설명할 수 있는 핵심 조건만 남긴다.

### 최소 실험 조건

우선순위는 다음 6개다.

1. `baseline_chunk512`
   - 기본 정제만 적용한 512 chunk 기준선
2. `clean_chunk512`
   - 공백, 헤더/푸터, 목차 점선, 페이지 번호 등 노이즈 제거 후 비교
3. `clean_context_injection_chunk512`
   - chunk 앞에 사업명, 발주기관, 섹션명을 붙였을 때의 효과 확인
4. `clean_tag_filter_chunk512`
   - RFP 섹션 태그와 metadata filter를 적용했을 때의 효과 확인
5. `multi_chunk_256_512_1024`
   - 질문 유형별로 small/medium/large chunk를 함께 검색했을 때의 효과 확인
6. `table_summary_on`
   - 평가기준, 배점, 제출서류, 일정표 같은 표 요약 chunk를 추가했을 때의 효과 확인

### 실험 결과 로그 포맷

각 실험은 같은 질문셋으로 돌리고, retrieval 결과를 같은 포맷으로 저장한다.

```text
experiment_id, question_id, retrieved_docs, retrieved_chunks, retrieval_ms
```

예시:

```text
baseline_chunk512, Q001, ["문서A", "문서B"], ["chunk_1", "chunk_7"], 42.3
clean_tag_chunk512, Q001, ["문서A", "문서C"], ["chunk_9", "chunk_2"], 38.1
```

이 결과를 `data/eval/*.csv`의 `ground_truth_docs`와 비교해 지표를 계산한다.

### 확인할 지표

전처리 담당 관점에서 우선 확인할 지표는 다음이다.

- `Hit Rate@5`: 정답 문서가 top-5 안에 들어오는가
- `MRR`: 정답 문서가 몇 번째에 위치하는가
- `nDCG`: 관련 문서가 상위에 잘 정렬되는가
- `Context Recall`: 정답 근거가 검색 context에 포함되는가
- `retrieval_ms`: 검색 속도가 실사용 가능한 수준인가

### 해석 기준

- `Hit Rate@5`가 오르면 전처리/태그가 정답 문서를 찾는 데 도움이 된 것이다.
- `MRR`이 오르면 정답 문서가 더 앞순위로 올라온 것이다.
- `Context Recall`이 낮으면 chunk가 너무 작거나, 섹션 분리/태그가 잘못됐을 가능성이 크다.
- `retrieval_ms`가 크게 늘면 실험 조건이 좋아 보여도 최종 채택 전에 속도 trade-off를 따져야 한다.
- 지표가 좋아지지 않는 전처리는 과감히 버린다.

### 내 결론 방식

최종 보고서에는 “전처리를 했다”가 아니라 다음 형태로 쓴다.

> `baseline_chunk512` 대비 `clean_context_injection_chunk512`에서 Hit@5와 MRR이 개선되어, 작은 chunk의 문맥 손실을 사업명/발주기관/섹션명 주입으로 완화할 수 있음을 확인했다.

핵심은 전처리 조건을 줄이고, 결과를 숫자로 증명하는 것이다.
## 개인 운영 원칙

- 전처리 변경은 반드시 실험명과 함께 기록한다.
- 변경 후 최소 샘플 평가를 돌려 지표 변화를 본다.
- 좋아 보이는 전처리라도 지표가 나빠지면 버린다.
- retrieval 담당자와 충돌하지 않게 baseline 검증 목적을 명확히 말한다.
- 최종 산출물은 `chunks.jsonl` 또는 `chunks.parquet`처럼 재사용 가능한 형태로 만든다.

## 기억할 문장

> 결과를 안 보고는 이 전처리가 좋은지 알 수 없다. 그래서 나는 전처리 담당이지만, 검색 결과로 전처리 품질을 증명한다.
