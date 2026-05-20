# P4 690 Expansion Execution Plan

## 목적

P4 250 검증 결과를 기준으로, 전체 690개 RFP를 HWPX 우선 파싱 기반 retrieval-ready corpus로 확장한다.
이번 단계의 목표는 모델 성능을 바로 끌어올리는 것이 아니라, Chroma 적재와 retrieval 실험이 안정적으로 돌아갈 수 있는 corpus를 만드는 것이다.

## 현재 기준

```text
P4 250: HWPX table-aware mini-pilot
P4 690: 같은 설계를 전체 corpus에 확장
Chroma DB: 공유 산출물이 아니라 재생성 가능한 index
source_store: generation DB가 아니라 선택적 상세 근거 저장소
```

## 실행 순서

```text
1. P4 250 validation 완료
2. G2B 보강 metadata 반영 규칙 확정
3. P4 690 corpus 생성
4. validation_report 확인
5. Chroma local index quick check
6. retrieval 100문항 quick check
7. 문제 chunk/table 유형 분석
8. 필요 시 table/fact logic 수정 후 재생성
```

## G2B 보강 metadata 반영 정책

팀원이 공유한 G2B/나라장터 데이터는 원문에서 직접 추출한 값이 아니므로 final fact로 바로 쓰지 않는다.
P4 690 확장 시에는 아래 필드만 external candidate metadata로 반영한다.

```text
입찰마감일시
공고번호
공고차수
```

공고번호 처리:

```text
원본 공고번호: 20240518650-001
external_notice_no = 20240518650-001
external_notice_no_base = 20240518650
external_notice_revision_no = 001
```

사용하지 않을 값:

```text
게시일자
나라장터_공고일
```

게시일자는 신뢰하지 않으며, embedding content, fact_candidates, final answer 근거로 사용하지 않는다.

## 중복 공고 선택 기준

동일 사업으로 보이는 후보가 여러 개일 때는 보수적으로 선택한다.

```text
1. 취소공고 제외
2. 입찰마감일시가 있는 공고 우선
3. 공고번호 suffix를 공고 차수로 분리
4. 게시일자 기준 최신 선택 금지
5. 취소건 제외 후 입찰마감일시 기준 최신 후보 우선
6. 사업명/기관명/연도 정합성이 낮으면 needs_review
```

권장 metadata:

```text
external_source = g2b_team_csv
external_notice_no
external_notice_no_base
external_notice_revision_no
external_bid_deadline
external_match_status = confirmed | needs_review | low_confidence
external_match_confidence = high | medium | low
```

## JSONL 반영 위치

G2B 보강값은 metadata에만 넣는다. 검증 전 external value를 content나 fact_candidates.content에 넣지 않는다.

```json
{
  "chunk_id": "...",
  "content": "임베딩할 텍스트",
  "metadata": {
    "external_source": "g2b_team_csv",
    "external_notice_no": "20240518650-001",
    "external_notice_no_base": "20240518650",
    "external_notice_revision_no": "001",
    "external_bid_deadline": "2024-05-28 14:00",
    "external_match_status": "confirmed",
    "external_match_confidence": "high"
  },
  "source_ref": {
    "source_store_id": "..."
  }
}
```

## ID와 역추적 검증

사람이 만든 ChunkID를 그대로 Chroma ids로 쓰면 중복 충돌이 생길 수 있다. P4에서는 hash 기반 stable id를 사용한다.

```text
doc_id = normalized source file + extension 기반 hash
chunk_id = doc_id + chunk_type + block_index + part_index + content_hash
source_store_id = doc_id + source_type + block_index + content_hash
```

필수 검증:

```text
duplicate_doc_id_count = 0
duplicate_chunk_id_count = 0
duplicate_source_store_id_count = 0
missing_source_store_ref = 0
chroma_id_unique = true
retrieved_chunk_to_source_ref_join_success = true
```

## Chroma 저장 위치 원칙

P3에서 확인한 병목은 Google Drive에 Chroma DB를 직접 쓰면서 발생했다. Chroma는 SQLite/HNSW 파일을 계속 갱신하므로 Drive 같은 동기화 파일시스템에 쓰면 멈추거나 극단적으로 느려질 수 있다.

```text
JSONL / predictions / csv / readme -> Google Drive 저장 가능
Chroma DB / embedding cache -> Google Drive 저장 금지
Chroma DB -> Colab /content 또는 GCP VM 로컬 디스크 사용
```

Colab 권장:

```python
CHROMA_DIR = Path("/content/chroma_retrieval_eval_p4")
```

GCP VM 권장:

```python
CHROMA_DIR = Path("/tmp/chroma_retrieval_eval_p4")
```

## P4 690 생성 후 확인할 것

```text
document_count = 690
parse_success_docs >= 689
source_format_counts 확인
chunk_count 과도 증가 여부 확인
jsonl_file_size_mb 확인
source_store size 확인
duplicate ids = 0
missing source ref = 0
external metadata confirmed/needs_review count 확인
sample 10개 문서 plain preview 확인
```

## retrieval quick check 기준

```text
R0: v1 clean text dense top5
R1: v2 HWPX table-aware dense top30 -> reranker top5
R2: v2 HWPX table-aware dense top30 + BM25 top30 -> RRF top30 -> reranker top5
```

해석은 점수만 보지 말고 실패 질문에서 어떤 chunk_type과 metadata가 부족했는지 같이 본다.
