# parsing_p4_hwpx_125 Retrieval-Ready Corpus

HWPX 우선 파싱을 적용한 P4 mini-pilot corpus입니다.

## 파일 설명

| 파일 | 설명 |
|---|---|
| `chunks_v1_125.jsonl` | clean text baseline retrieval index입니다. R0 비교 실험에 사용합니다. |
| `chunks_v2_125.jsonl` | HWPX table-aware structured retrieval index입니다. Chroma 적재 기본 입력입니다. |
| `source_store_v1_125.jsonl` | v1 상세 근거 조회용 파일입니다. Chroma metadata의 `source_store_id`로 연결할 때만 사용합니다. |
| `source_store_125.jsonl` | v2 상세 근거 조회용 파일입니다. 큰 table 구조는 여기에 보관하고 Chroma metadata에는 연결 key만 둡니다. |
| `metadata_light_125.xlsx` | 문서별 파싱 요약과 5,000자 preview를 담은 참고용 파일입니다. |
| `validation_report_v1.json` | v1 검증 결과입니다. |
| `validation_report.json` | v2 검증 결과입니다. |
| `manifest.json` | corpus 생성 조건과 파일명을 기록합니다. |
| `json_key_description.md` | 125 corpus의 JSON/JSONL key, metadata, source_store, fact/table 정책 설명서입니다. |
| `chroma_load_example.py` | Colab/GCP에서 `chunks_v2_125.jsonl`을 Chroma에 적재하는 실행 예시입니다. 버전 충돌 방어 코드를 포함합니다. |
| `embedding_retrieval_eval_p4_hwpx_125_quickcheck.ipynb` | `chunks_v2_125.jsonl`을 Chroma에 적재하고 KoE5 dense/BM25/RRF/reranker retrieval 실험을 실행하는 노트북입니다. |

## 사용 기준

- Chroma 적재 시 `chunk_id`는 `ids`, `content`는 `documents`, `metadata`는 `metadatas`로 사용합니다.
- retrieval 담당자는 기본적으로 `chunks_v2_125.jsonl`에서 `embed_enabled=true`인 record의 `content`를 임베딩 대상으로 사용합니다.
- `chunk_type=toc`는 구조 파악용으로 보존하되 기본 임베딩 대상에서 제외합니다.
- 기본 generation 입력은 Chroma가 반환한 `documents + metadatas`입니다.
- 표 원형, 긴 원문 근거, UI 원문 보기, 정성평가처럼 Chroma chunk만으로 부족할 때만 `source_ref.source_store_id`로 `source_store_125.jsonl`을 조회합니다.
- `rows`, `full_table_json`, 긴 원문, OCR 전문은 Chroma metadata에 넣지 않습니다.
- G2B 보강 메타데이터는 `data/g2b_master_cleaned.csv`에서 공고번호와 괄호 안 `입찰마감일시`만 사용합니다. `게시일시`는 사용하지 않습니다.
- 원본 RFP, source_store, Chroma DB, embedding cache는 GitHub 업로드 대상이 아닙니다.

## Validation Summary

### v1

```json
{
  "output_dir": "/Users/apple/Desktop/codeit/project_2nd/chatbot/outputs/parsing_p4_hwpx_125",
  "version": "v1",
  "document_count": 125,
  "parse_success_docs": 125,
  "parse_failed_docs": 0,
  "source_format_counts": {
    "hwpx": 113,
    "pdf": 12
  },
  "total_table_count": 13585,
  "total_image_count": 609,
  "chunk_count": 13590,
  "source_store_count": 4977,
  "duplicate_doc_id_count": 0,
  "duplicate_chunk_id_count": 0,
  "duplicate_source_store_id_count": 0,
  "missing_source_store_ref": 0,
  "missing_doc_key_count": 0,
  "embed_enabled_count": 13534,
  "chunk_type_counts": {
    "toc": 56,
    "text": 13534
  },
  "avg_content_len": 762.41,
  "p50_content_len": 939,
  "p95_content_len": 997,
  "max_content_len": 1000,
  "chunks_jsonl_file_size_mib": 38.14,
  "source_store_file_size_mib": 25.68,
  "date_policy": "bid_deadline_only; posted date and bid-start date are not used",
  "created_at": "2026-05-21 11:07:26",
  "eval_physical_source_docs_included": 40,
  "expected_eval_physical_source_docs": 40,
  "additional_sampled_docs": 85,
  "g2b_match_status_counts": {
    "no_confident_match": 56,
    "matched_active": 48,
    "ambiguous_active": 21
  },
  "g2b_active_match_count": 48,
  "g2b_bid_deadline_count": 37,
  "g2b_cancelled_only_count": 0,
  "g2b_ambiguous_active_count": 21,
  "status": "PASS",
  "fail_reasons": []
}
```

### v2

```json
{
  "output_dir": "/Users/apple/Desktop/codeit/project_2nd/chatbot/outputs/parsing_p4_hwpx_125",
  "version": "v2",
  "document_count": 125,
  "parse_success_docs": 125,
  "parse_failed_docs": 0,
  "source_format_counts": {
    "hwpx": 113,
    "pdf": 12
  },
  "total_table_count": 13585,
  "total_image_count": 609,
  "chunk_count": 22341,
  "source_store_count": 16867,
  "duplicate_doc_id_count": 0,
  "duplicate_chunk_id_count": 0,
  "duplicate_source_store_id_count": 0,
  "missing_source_store_ref": 0,
  "missing_doc_key_count": 0,
  "embed_enabled_count": 19188,
  "chunk_type_counts": {
    "toc": 56,
    "text": 5795,
    "fact_candidates": 892,
    "table": 15598
  },
  "avg_content_len": 541.37,
  "p50_content_len": 433,
  "p95_content_len": 991,
  "max_content_len": 1000,
  "chunks_jsonl_file_size_mib": 55.14,
  "source_store_file_size_mib": 86.54,
  "date_policy": "bid_deadline_only; posted date and bid-start date are not used",
  "created_at": "2026-05-21 11:07:26",
  "eval_physical_source_docs_included": 40,
  "expected_eval_physical_source_docs": 40,
  "additional_sampled_docs": 85,
  "g2b_match_status_counts": {
    "no_confident_match": 56,
    "matched_active": 48,
    "ambiguous_active": 21
  },
  "g2b_active_match_count": 48,
  "g2b_bid_deadline_count": 37,
  "g2b_cancelled_only_count": 0,
  "g2b_ambiguous_active_count": 21,
  "fact_status_counts": {
    "extracted": 892
  },
  "fact_confidence_counts": {
    "high": 746,
    "medium": 146
  },
  "fact_type_counts": {
    "document_summary": 147,
    "budget": 104,
    "duration": 118,
    "submission_documents": 113,
    "submission_logistics": 118,
    "eligibility": 118,
    "business_type": 125,
    "bid_deadline": 49
  },
  "low_confidence_fact_embedded_count": 0,
  "table_role_counts": {
    "weak_table": 2989,
    "retrieval_signal": 10525,
    "generic_table": 1976,
    "layout_or_toc": 108
  },
  "suppressed_table_chunk_count": 3097,
  "row_type_counts": {
    "group_title": 22556,
    "blank": 4851,
    "body": 44642,
    "header_candidate": 22153,
    "note": 326
  },
  "merged_cell_count": 80365,
  "status": "PASS",
  "fail_reasons": []
}
```
