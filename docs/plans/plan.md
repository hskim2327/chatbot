# RFP RAG 프로젝트 설계 플랜

## 1. 프로젝트 목표

100개 규모의 실제 기업/정부 제안요청서(RFP)와 메타데이터를 기반으로, 입찰 컨설턴트가 필요한 정보를 빠르게 찾고 판단할 수 있는 RAG 서비스를 구축한다.

핵심 목표는 큰 LLM을 무조건 사용하는 것이 아니라, 제한된 자원 안에서 전처리 품질, 청킹, 자동 태그, 검색 전략, 평가 기반 튜닝으로 최대 성능을 뽑아내는 것이다.

노션 가이드라인 기준으로는 API 기반 접근을 먼저 시도하되, LLM 튜닝은 성능 우위가 아니라 시도와 비교 자체에 의미가 있는 선택 실험으로 둔다. 최종 완성도는 검색 품질, 근거 기반 답변, 비용/속도 제어, 그리고 UI까지 이어지는 서비스화로 판단한다.

주요 사용자 시나리오는 다음과 같다.

- 특정 RFP의 사업명, 발주기관, 예산, 입찰 마감일, 계약 기간을 빠르게 확인한다.
- 참가 자격, 제출 서류, 제안서 작성 지침, 평가 기준과 배점을 근거 문장과 함께 확인한다.
- 여러 RFP를 비교하여 고객사에 추천할 만한 입찰 기회를 선별한다.
- 문서에 없는 내용은 추정하지 않고, 근거 없음으로 명확히 답변한다.

## 2. 확인된 데이터와 제약

현재 확인된 로컬 자료 기준:

- 최신 메타데이터 파일: `data/data_list_advanced.xlsx`
- 이전 참고 메타데이터 파일: `data/data_list_reparsed.xlsx`
- 평가셋 폴더: `data/eval`
- 원본 묶음: `data/original_data_list.zip`
- 최신 메타데이터 행 수: 690개 문서 수준
- 파일 형식: HWP 665개, PDF 25개
- 메타데이터 컬럼: 공고 번호, 공고 차수, 사업명, 사업 금액, 발주 기관, 공개 일자, 입찰 참여 시작일, 입찰 참여 마감일, 사업 요약, 파일형식, 파일명, 텍스트
- 평가 CSV: 38개 배치, 총 1,100문항
- 평가 CSV 컬럼: `id`, `type`, `difficulty`, `question`, `ground_truth_answer`, `ground_truth_docs`, `metadata_filter`, `history`
- 평가 CSV의 `ground_truth_docs`에 실제 정답 문서로 등장하는 unique 문서는 확장자 정규화 후 62개다.

주의할 점:

- `data_list_advanced.xlsx`의 `텍스트`는 690개 모두 채워져 있지만, 원본 구조 전체를 보장하는 DB 원천으로 단정하지 않는다. 메타데이터와 빠른 sanity check에는 활용하되, 최종 구조화 DB는 원본 HWP/PDF 재추출 결과와 비교한다.
- 이전 `data_list_reparsed.xlsx`의 98개와 평가셋 누락 3개로 추정했던 101개 기준은 과거 subset으로만 취급한다.
- 전체 DB 구축 기준은 `advanced_690`이며, 반복 실험 속도를 위해 `eval_answer_docs_62`를 포함한 pilot subset을 먼저 사용할 수 있다.
- 원본 RFP 전체 데이터셋과 대용량 파싱 산출물은 용량 문제 때문에 GitHub에 올리지 않는다.
- 팀 실험용 GCP/GCS 환경에는 원본 데이터를 업로드할 수 있다.
- Chroma DB, 원본 텍스트 캐시, API key, `.env` 파일은 GitHub에 올리지 않는다.
- 소량의 테스트용 원문 출력이 포함된 노트북은 공유 가능하되, 전체 데이터셋이나 대량 원문 산출물은 포함하지 않는다.

## 3. 전체 아키텍처

권장 파이프라인은 다음 순서로 구성한다.

1. 데이터 로딩
2. RFP 특화 전처리
3. 문서 구조 기반 청킹
4. 자동 태그 생성
5. Chroma 인덱싱
6. Retrieval
7. Reranking 또는 soft boost
8. Context assembly
9. 구조화 추출 및 답변 생성
10. 평가 및 실험 로그 저장

큰 방향은 `문서 품질 개선 -> 검색 성능 개선 -> 생성 신뢰도 개선 -> 속도/비용 최적화` 순서로 진행한다.

## 4. Chroma 인덱싱 전략

문서 규모가 100개 안팎이므로 벡터DB는 Chroma를 사용한다. Qdrant나 Milvus보다 운영이 가볍고, 실험 반복 속도가 빠르다.

임베딩 실험 운영 원칙:

- 1차 반복 실험은 GCP VM 또는 Colab L4에서 KoE5(`nlpai-lab/KoE5`) + Chroma로 수행한다.
- 태깅, 청킹, retrieval 성능 윤곽이 잡힌 뒤 API 임베딩 또는 API 생성 모델을 붙여 최종 품질을 확인한다.
- `text-embedding-3-small`은 API 기반 비교 baseline 또는 최종 API 경로 검증용으로 사용하고, 반복 ablation의 기본값은 KoE5로 둔다.

권장 collection 구성:

- `rfp_small_256`: 날짜, 금액, 제출서류, 자격요건처럼 짧은 근거 탐색용
- `rfp_medium_512`: 일반 QA 기본 검색용
- `rfp_large_1024`: 과업범위, 리스크, 요약처럼 넓은 문맥이 필요한 질의용
- `rfp_table_summary`: 평가 기준, 배점, 일정표, 제출서류 표의 요약 인덱스

각 chunk metadata에는 아래 항목을 저장한다.

- `notice_id`
- `round`
- `project_name`
- `issuer`
- `budget`
- `published_at`
- `bid_start`
- `bid_deadline`
- `file_type`
- `filename`
- `section_path`
- `section_type`
- `chunk_type`
- `chunk_size`
- `parent_chunk_id`
- `tags`
- `page_or_position`
- `has_table`
- `has_amount`
- `has_date`
- `has_requirement_keyword`

Git 관리 정책:

- `chroma_db/`는 `.gitignore`에 포함한다.
- 원본 텍스트 캐시, 파싱 결과 전문, RFP 전문이 포함된 parquet/json 파일도 `.gitignore`에 포함한다.
- repo에는 재현 코드, 비식별 샘플, 평가 스크립트, 보고서만 남긴다.

## 5. RFP 특화 전처리

RFP는 일반 문서가 아니라 입찰 판단 문서이므로, 단순 텍스트 정제보다 섹션과 의무 조건 보존이 중요하다.

우선 태깅할 섹션:

- 사업개요
- 과업범위
- 입찰참가자격
- 제출서류
- 제안서 작성지침
- 평가기준 및 배점
- 사업금액
- 계약기간
- 입찰 마감일
- 보안요구사항
- 하자보수/유지보수
- 별첨/서식

전처리 규칙:

- 반복 헤더, 푸터, 페이지 번호, 목차 점선, 의미 없는 공백과 줄바꿈을 제거한다.
- 한글 인코딩은 UTF-8 기준으로 통일한다.
- 날짜, 금액, 기관명, 공고번호는 원문값과 정규화값을 함께 저장한다.
- `필수`, `하여야 한다`, `제출`, `준수`, `감점`, `배점`, `평가`, `자격`, `보안` 같은 의무/평가 키워드를 태그로 저장한다.
- 표는 단순 문자열로 뭉개지 않도록 Markdown table 또는 row-wise text로 변환한다.
- 작은 chunk에는 `[사업명 | 발주기관 | 섹션명 | 파일명]`을 앞에 붙이는 context injection을 적용한다.
- 표나 복잡한 수치 데이터는 별도의 요약 chunk를 만들어 `chunk_type=summary`로 저장한다.

HWP/PDF 처리 방침:

- 1차: `data_list_advanced.xlsx`의 메타데이터와 텍스트를 빠른 sanity check 기준으로 활용
- 2차: 원본 HWP/PDF에서 텍스트를 재추출해 길이, 섹션, 날짜, 금액, 기관명 보존 여부를 비교
- 3차: HWP는 `pyhwpx`가 가능한 Windows + 한컴 정식 설치 환경이면 우선 시도하되, Viewer/Colab/GCP/headless 환경에서는 실패할 수 있으므로 `olefile` 기반 BodyText 직접 추출 fallback을 유지
- 4차: HWP 내부 제어 정보가 한자처럼 디코딩되는 artifact는 추출 직후 제거하고, 이후 cleaner 단계에서 목차/공백/중복/메타데이터 alias를 정규화
- 5차: 추출 실패 문서는 실패 사유를 기록하고 `parser_status=failed` 또는 `needs_review`로 관리

구조화 DB 고도화 원칙:

- DB 원천 산출물은 Excel이 아니라 JSONL로 둔다.
- `rfp_chunks.jsonl`은 chunk 1개를 JSON 1줄로 저장하고, `text_chunk`, `table_chunk`, `image_ocr_chunk`, `section_summary_chunk`를 `chunk_type`으로 구분한다.
- Chroma에는 `content`만 embedding 대상으로 넣고, 복잡한 `table_rows`, OCR 원문, 원본 위치 정보는 JSONL 원본에 보존한다.
- 실험 로그는 `retrieval_experiments.csv` 하나에 append한다.
- 초기 반복 실험은 `pilot_subset`으로 빠르게 검증하되, 최종 확장 대상은 `advanced_690` 전체 corpus다.

추출 이후 cleaner 단계:

- BR 태그와 문단 구분 정규화
- 불필요 HTML/table wrapper 제거
- 목차 전용 블록 제거 또는 별도 `toc_chunk` 분리
- 섹션 박스/헤더를 `section_path`로 정규화
- PUA, HWP artifact, 비정상 공백 제거
- 중복 셀/중복 문장 병합
- 기관명, 사업명, 파일명 표기 차이를 metadata alias로 매핑

## 6. Retrieval 설계

검색은 단일 벡터 top-k만 사용하지 않는다. RFP 질의는 고유명사, 숫자, 날짜, 섹션명이 중요하므로 dense search와 sparse search를 결합한다.

기본 검색 흐름:

1. Query 분석 및 metadata filter 생성
2. Chroma dense search
3. BM25 sparse search
4. RRF로 dense/sparse 결과 병합
5. section/tag 기반 soft boost
6. 중복 chunk 제거
7. parent chunk 확장
8. 최종 top-k context assembly

질문 유형별 전략:

- 예산, 마감일, 계약기간: metadata filter + BM25 + small chunk 우선
- 제출서류, 참가자격: section tag + small/medium chunk 우선
- 과업범위, 요구사항 요약: medium/large chunk + parent context 확장
- 평가 기준/배점: table summary + section tag 우선
- 문서 비교: 문서별 독립 검색 후 비교표 생성
- 후속 질문: `history` 기반 query rewriting 적용

실험할 검색 기법:

- top-k 3, 5, 10 비교
- MMR로 중복 context 감소
- query rewriting
- multi-query
- HyDE는 비용 대비 효과가 확인될 때만 제한적으로 사용
- reranker는 GCP/L4 환경에서 우선 실험하고, API 예산이 부족하면 RRF + soft boost를 우선 최적화

## 7. Generation 설계

노션 가이드라인의 방향은 API를 먼저 시도하고, LLM 튜닝은 성능 향상 보장보다 시도와 비교 가치가 있는 옵션으로 다루는 것이다. 따라서 생성 단계는 API 모델을 우선 기준선으로 삼고, 로컬/튜닝 모델은 여력이 있을 때 비교 실험으로 둔다.

API 사용 시 역할을 분리한다.

- `text-embedding-3-small`: API 임베딩 baseline 및 최종 비교
- `gpt-5-nano`: query rewrite, 질의 유형 분류, 태그 보정, 간단 추출
- `gpt-5-mini`: 최종 답변, 구조화 추출, 복합 요약, 비교 답변

답변 원칙:

- 주어진 context 안에서만 답변한다.
- 근거가 없으면 모른다고 답한다.
- 핵심 정보에는 citation을 붙인다.
- 날짜, 금액, 제출서류, 평가기준은 추정하지 않는다.
- 긴 답변보다 컨설턴트가 바로 판단할 수 있는 구조화된 답변을 우선한다.

구조화 추출 스키마:

- `project_name`
- `issuer`
- `budget`
- `bid_deadline`
- `contract_period`
- `eligibility_requirements`
- `required_documents`
- `evaluation_criteria`
- `scope_of_work`
- `security_requirements`
- `risks`

각 필드는 다음 구조를 가진다.

```json
{
  "value": "추출값 또는 unknown",
  "confidence": 0.0,
  "citations": ["문서명/섹션/위치"]
}
```

## 8. 평가 지표

기본 평가 지표는 `3_RAG_평가지표_및_해석하기.ipynb`를 따른다.

Retrieval 지표:

- `Hit Rate@5`
- `MRR`
- `nDCG`
- `Context Precision`
- `Context Recall`

Generation 지표:

- `Faithfulness`
- `Answer Relevance`

효율/운영 지표:

- `retrieval_ms`
- `rerank_ms`
- `llm_ms`
- `total_ms/P95`
- `time_to_first_token` 가능하면 추가
- `cost_per_query`
- `tokens_per_query`

평가 방식:

- `data/eval`의 1,100문항을 유형과 난이도별로 나누어 평가한다.
- baseline은 dense-only Chroma 검색으로 잡는다.
- 이후 변경은 한 번에 하나씩 적용하고 지표 변화를 기록한다.
- 실패한 질문만 따로 모아 error analysis를 수행한다.

Ablation 목록:

- chunk size 단일 vs multi-size
- 자동 태그 off/on
- context injection off/on
- dense only vs BM25+dense
- RRF off/on
- reranker off/on
- table summary off/on
- `gpt-5-nano` vs `gpt-5-mini` 역할 분리

성공 기준 예시:

- `Hit Rate@5` 0.90 이상 도전
- `MRR`, `nDCG` 개선 폭을 보고 리랭킹 채택 여부 결정
- `Faithfulness`가 낮으면 생성 모델보다 context 품질과 프롬프트 제약을 먼저 점검
- `total_ms/P95`가 과도하게 높으면 reranker, top-k, multi-query 사용을 제한

## 9. GCP VM 운영 계획

`GCP_VM_설정_실습.ipynb` 기준으로 GCP는 실험 및 팀 공용 실행 환경으로 사용한다.

기본 운영 원칙:

- G2/L4 GPU VM은 사용하지 않을 때 반드시 중지한다.
- JupyterHub를 사용해 팀원별 독립 계정으로 접속한다.
- 포트는 기본적으로 8000번을 사용한다.
- 공용 관리자 환경에 모두를 억지로 맞추기보다, 팀원별 가상환경을 만들고 커널로 등록한다.
- GPU가 필요한 작업은 임베딩/reranker/local model 실험으로 제한한다.
- Colab L4는 개인 반복 실험 환경으로 사용 가능하며, KoE5 임베딩/Chroma 인덱싱/retrieval ablation을 빠르게 돌리는 용도로 우선 사용한다.

권장 환경 운영:

- 관리자는 NVIDIA 드라이버, CUDA, JupyterHub, 기본 Python만 관리한다.
- 팀원은 각자 홈 디렉터리에 venv를 만들고 Jupyter kernel로 등록한다.
- 공통 의존성은 `requirements.txt` 또는 `environment.yml`로 버전을 고정한다.
- 모델 캐시와 Chroma DB 위치를 합의해 중복 다운로드와 저장소 낭비를 줄인다.

## 10. 팀 역할 분배

6명 팀은 모듈별 DRI를 두되, 검색/생성/평가는 반드시 교차 리뷰한다.

권장 역할:

1. 데이터/HWP·PDF 추출/보안 DRI
2. RFP 전처리/섹션 태깅 DRI
3. Chroma 인덱싱/청킹 실험 DRI
4. Retrieval/BM25/RRF/context assembly DRI
5. Generation/프롬프트/구조화 추출 DRI
6. Evaluation/latency/cost/report/demo DRI

운영 방식:

- 매일 30분은 진행상황 나열이 아니라 성능 병목 토론으로 사용한다.
- 각 DRI는 자기 모듈의 지표 변화를 기록한다.
- 중요한 의사결정은 보고서에 남긴다.
- 개인 협업일지에는 담당 업무, 실패한 실험, 배운 점, 다음 액션을 기록한다.

## 11. 일정 추정

근거:

- 문서 규모: 최신 메타데이터 기준 690개 RFP
- 평가셋: 1,100문항
- 평가 정답 문서: `ground_truth_docs` 기준 unique 62개
- 데이터 형식: HWP 665개, PDF 25개
- 벡터DB: Chroma
- API 제약: `gpt-5-mini`, `gpt-5-nano`, `text-embedding-3-small`, 팀별 $20 제한
- 실행 환경: GCP VM/L4 사용 가능
- 팀 규모: 6명

추정:

- 최소 4일: pilot subset 기반 Chroma PoC, 기본 전처리, Streamlit 데모, 평가 일부 수행
- 중앙 7일: HWP 재추출 검증, 자동 태그, hybrid search, ablation, 보고서 작성
- 최대 10일: 표 처리/OCR 일부/리랭커 비교, `advanced_690` 전체 확장, 전체 평가셋 평가, 발표자료 고도화

권장 마일스톤:

- Day 1: 데이터 로딩, 보안 정책, baseline dense retrieval
- Day 2: RFP 전처리, 청킹, Chroma 인덱싱
- Day 3: BM25/RRF, metadata filter, 자동 태그
- Day 4: generation, citation, Streamlit 데모
- Day 5: 평가 자동화, latency/cost 로깅
- Day 6: ablation 및 실패 사례 분석
- Day 7: 최종 설정 확정, 보고서/발표 정리

## 12. 제출물 정책

제출물:

- 구현한 RAG 시스템을 재현할 수 있는 GitHub Repository 링크
- 프로젝트 진행 과정, 결과, 성과, 개선 사항이 포함된 보고서 PDF
- 개인 협업일지 링크 또는 PDF

금지:

- 원본 RFP 파일 업로드
- 원본 RFP 전문이 포함된 파싱 결과 업로드
- Chroma DB 업로드
- API key 또는 `.env` 업로드
- 비식별화되지 않은 원문 예시를 보고서/README에 포함

허용:

- 코드
- 실행 방법
- 비식별 샘플
- 성능표
- 평가 결과 요약
- 실패 사례 유형화
- 전처리/청킹/검색/생성 설계 설명

## 13. 최종 판단 기준

이 프로젝트에서 좋은 결과물은 단순히 답변이 자연스러운 챗봇이 아니다.

좋은 결과물은 다음을 증명해야 한다.

- RFP의 특성을 이해하고 전처리에 반영했다.
- Chroma 기반 검색 구조를 문서 규모에 맞게 단순하고 재현 가능하게 설계했다.
- 청킹 사이즈, 자동 태그, hybrid search가 실제 지표를 개선했다.
- 답변은 근거 기반이며, 문서에 없는 내용은 거절한다.
- 속도와 비용을 측정했고, 품질과 효율의 트레이드오프를 설명할 수 있다.
- API 기준선을 확보한 뒤, GCP/Colab L4 + KoE5 반복 실험으로 retrieval을 최적화했다.
- LLM 튜닝은 최종 성능 우위가 아니라 비교 실험과 학습 가치 중심으로 시도 여부를 판단했다.
- 가능하면 Streamlit 등 UI까지 구현해 실제 서비스 흐름을 보여준다.
- 팀원 6명이 역할을 나누되, 성능 개선 과정은 함께 토론하고 기록했다.
## P2 이후 테이블 구조 고도화 메모

- 현재 `parsing_p2_250`의 table block은 실제 산출물 기준 `structured_data.rows`와 `structured_data.raw_lines` 중심으로 보존한다.
- 발표용 HTML 예시도 실제 P2 구조와 맞추기 위해 `rows/raw_lines`로 설명한다.
- 다음 버전에서 표 구조 복원이 안정화되면 `columns`와 `body_text`를 추가 후보로 검토한다.
  - `columns`: 표의 헤더/컬럼명을 분리해 저장
  - `body_text`: 행/열 정보를 자연어 검색에 유리한 문장형 텍스트로 변환
- 단, `columns/body_text`는 현재 P2 확정 구조가 아니라 향후 DB 고도화 후보로 관리한다.

## P3 테이블 구조화 고도화 계획

P2는 표 내부 원문 텍스트를 `rows/raw_lines` 중심으로 보존하는 단계다. P3는 이를 유지하면서, 신뢰도 높은 표에만 `columns/body_text`를 추가해 표 의미 구조를 더 잘 활용하는 버전으로 설계한다.

### P3 목표

- `raw_lines`: 표 내부 원문 줄을 최대한 그대로 보존한다.
- `rows`: 표의 행 단위 텍스트를 유지한다.
- `columns`: 헤더가 명확한 표에서만 컬럼명을 분리한다.
- `body_text`: 행/열 관계를 자연어 문장으로 변환해 임베딩 검색 친화도를 높인다.
- `table_type`: 제출서류표, 평가기준표, 일정표, 예산표, 일반표 등으로 표 유형을 분류한다.
- `table_parse_confidence`: 컬럼/행 복원 신뢰도를 기록해 낮은 신뢰도 표는 기존 `rows/raw_lines`만 사용한다.

### 설계 원칙

- P2의 `rows/raw_lines`는 원본 보존용으로 계속 유지한다.
- `columns/body_text`는 기존 값을 대체하지 않고 검색 강화용 보조 필드로 추가한다.
- 모든 표에 강제로 적용하지 않고, 헤더와 행 구분이 명확한 표부터 제한적으로 적용한다.
- 잘못 구조화된 표는 retrieval 노이즈가 될 수 있으므로 `table_parse_confidence`가 낮으면 Chroma 적재에서 `body_text` 사용을 제외한다.
- P3 성능은 `v2_p2` 대비 retrieval 지표와 정성 샘플을 함께 비교해 채택 여부를 결정한다.

### 예시 구조

```json
"structured_data": {
  "raw_lines": ["구분 | 제출서류 | 비고", "기술제안 | 제안서, 발표자료 | 정량/정성 평가"],
  "rows": [{"text": "기술제안 | 제안서, 발표자료 | 정량/정성 평가"}],
  "columns": ["구분", "제출서류", "비고"],
  "body_text": "기술제안 제출서류는 제안서와 발표자료이며, 정량/정성 평가에 사용됩니다.",
  "table_type": "submission_documents",
  "table_parse_confidence": 0.87
}
```
