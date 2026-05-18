# RFP 자동 태깅 우선 실험 공유 노트

## 1. 현재 판단

이번 RAG 프로젝트에서 자동 태깅은 최종 성능에 영향을 줄 수 있다. 다만 태깅 자체가 성능을 올리는 것이 아니라, 검색 단계에서 `metadata filter`, `soft boost`, `routing`, `context injection` 신호로 실제 사용될 때 성능 변수로 작동한다.

따라서 전처리 품질을 감으로 판단하지 않고, 같은 조건에서 태깅 방식만 바꿔 retrieval 지표를 비교한다.

## 2. 먼저 확인할 것

텍스트가 있는 21개 문서가 실제 원본 HWP/PDF와 일치하는지 먼저 확인한다.

확인 기준:

- `data_list_reparsed.xlsx`의 `파일명`이 원본 폴더에 존재하는지 확인
- 원본 HWP/PDF에서 텍스트를 재추출해 엑셀의 `텍스트`와 비교
- 정규화 후 길이 비율 확인
- 사업명, 발주기관, 주요 날짜/금액 키워드 보존 여부 확인
- 샘플 anchor 문장이 원본 추출 텍스트에 포함되는지 확인

현재 1차 파일명 기준으로는 텍스트가 있는 21개 문서 모두 원본 폴더에 존재하는 것으로 확인했다. 2차 텍스트 재추출 비교 결과는 `outputs/original_text_match_check.csv`에 저장해 관리한다.

## 3. 실험 설계

초기 실험은 변수를 줄이기 위해 다음 조건을 고정한다.

- 대상 문서: 원본 일치성 검증을 통과한 텍스트 문서
- chunk size: 512
- embedding: `nlpai-lab/KoE5`
- vector DB: Chroma
- 비교 변수: 태깅 사용 방식

비교 실험:

- `T0_no_tag_512`: 태그 없이 512 chunk + dense Chroma 검색
- `T1_rule_tag_512`: 키워드/섹션명 기반 rule tag를 soft boost로 사용
- `T2_rule_metadata_tag_512`: rule tag + metadata/section 신호를 함께 soft boost로 사용

LLM 기반 태그 보정은 비용과 속도 부담이 있으므로, T0~T2 결과를 본 뒤 필요할 때만 추가한다.

## 4. 확인할 지표

태깅 효과는 다음 retrieval 지표로 판단한다.

- `Hit@5`: 정답 문서가 top-5 안에 들어오는지
- `MRR`: 정답 문서가 얼마나 앞순위에 나오는지
- `nDCG`: 관련 문서가 상위에 잘 정렬되는지
- `Context Recall`: 정답 근거가 검색 context에 포함되는지
- `retrieval_ms`: 검색 속도가 실사용 가능한 수준인지

결과는 하나의 CSV에 append한다.

저장 위치:

```text
outputs/retrieval_experiments.csv
```

## 5. 로컬 환경 가능 여부

Colab L4 환경에서 진행한다.

확인된 환경:

- GPU: Colab L4
- VRAM: 약 24GB급 환경
- torch: Colab GPU 런타임 CUDA 빌드 사용

KoE5는 로컬 임베딩이므로 OpenAI API key 없이 실행 가능하다. Hugging Face/LangChain 계열 버전은 미션14 수정 베이스라인 조합을 기준으로 고정한다. 현재 torch가 CUDA를 잡지 못하면 CPU로 실행되므로, Colab 메뉴에서 Runtime type을 GPU/L4로 선택하고 `torch.cuda.is_available()`를 확인해야 한다.

예상 소요 시간:

- 최소: 20~40분
- 중앙: 1~2시간
- 최대: 3~5시간

근거:

- 텍스트 문서 21개
- 문서당 평균 약 4.5만 자
- 512 chunk 기준 수백~1천여 chunk 예상
- rule tagging과 Chroma 인덱싱은 CPU로 충분
- 시간이 늘어나는 주요 원인은 HWP 원본 재추출 실패, 원본-엑셀 텍스트 비교 로직 보정, KoE5 최초 모델 다운로드와 임베딩 계산 시간이다.

## 6. 팀 내 역할 정리

내 역할은 단순 전처리가 아니라, RFP 문서를 검색 가능한 구조로 바꾸고 그 전처리/태깅이 실제 retrieval 성능을 개선하는지 검증하는 것이다.

retrieval 담당자와의 역할 경계:

- 내가 담당: 원본 텍스트 품질 확인, RFP 전처리, 자동 태깅, 512 chunk 생성, Chroma baseline 인덱싱, 태깅 ablation 결과 확인
- retrieval 담당자 담당: 최종 검색 전략, BM25/RRF, reranker, query rewriting, context assembly 고도화

팀에는 다음처럼 공유한다.

> 전처리 품질을 감으로 판단하지 않기 위해, 우선 원본 문서와 텍스트 일치성을 확인한 뒤 512 chunk로 고정하고 태깅 방식만 바꿔 retrieval 지표를 비교하겠습니다. 최종 retrieval 고도화는 retrieval 담당자와 맞춰서 넘기겠습니다.

## 7. 주의사항

- 원문 출력은 정성평가를 위해 로컬 노트북에서는 유지한다.
- 원문 output이 저장된 `.ipynb`는 GitHub 업로드 전 반드시 output clear 한다.
- 원본 RFP 파일, 원문 전문, Chroma DB, `.env`, API key는 외부 공유하지 않는다.
- 태깅을 hard filter로 바로 쓰면 오태깅 때문에 정답 chunk가 제외될 수 있으므로, 초기 실험에서는 soft boost로 사용한다.

## 8. 협업일지용 요약

오늘은 RFP 전처리/태깅 파트의 실험 방향을 정리했다. 자동 태깅이 실제 성능에 영향을 주는지 확인하기 위해 chunk size와 임베딩 모델을 KoE5로 고정하고, 태깅 방식만 바꾸는 ablation 실험을 설계했다. 먼저 텍스트가 있는 21개 문서가 원본 HWP/PDF와 일치하는지 검증한 뒤, 통과 문서를 대상으로 `T0_no_tag_512`, `T1_rule_tag_512`, `T2_rule_metadata_tag_512`를 비교할 계획이다. 지표는 `Hit@5`, `MRR`, `nDCG`, `Context Recall`, `retrieval_ms`를 사용한다.
