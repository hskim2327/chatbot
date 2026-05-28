# RAG Codeit Project - YSY Branch

이 브랜치는 팀장님 repo에서 현재 공유 기준으로 사용하는 RFP RAG 작업 브랜치입니다. parsing/corpus 생성 로직과 retrieval/generation 실험 코드를 함께 확인할 수 있도록 정리했습니다.

GitHub에는 코드, 노트북, 재현용 스크립트, 설명 문서만 포함합니다. 원본 RFP, 생성 corpus JSONL, source_store JSONL, Chroma DB, embedding cache, API key는 올리지 않습니다.

## 현재 기준

```text
parsing/corpus 생성   src/parsing/, notebooks/parsing/, scripts/corpus/20260528/, scripts/g2b/
retrieval/generation  notebooks/rag/, src/generation/, docs/plans/, docs/notes/
```

- corpus 생성/보정/검증 로직은 `scripts/corpus/20260528/`와 `scripts/g2b/`를 기준으로 확인합니다.
- retrieval/generation 실험은 `notebooks/rag/`와 `src/generation/`을 기준으로 확인합니다.
- 대용량 산출물은 별도 공유 드라이브에서 받아 로컬, Colab, GCP 런타임에 배치해서 사용합니다.

## 최종 Slim Corpus 기준

아래 값은 최종 로컬 산출물의 `chunks_v2_*.jsonl` raw 파일 크기 기준입니다. 압축해서 공유하는 경우 실제 전달 파일은 더 작을 수 있습니다.

| corpus | slim chunks 파일 | chunks 수 | raw JSONL 크기 | gzip 참고 크기 |
|---|---|---:|---:|---:|
| 125 | `chunks_v2_125.jsonl` | 19,853 | 80.86 MiB | 6.45 MiB |
| 250 | `chunks_v2_250.jsonl` | 36,944 | 162.37 MiB | 10.73 MiB |
| 690 | `chunks_v2_690.jsonl` | 106,776 | 476.88 MiB | 30.51 MiB |

실험용 embedding에는 slim corpus의 `chunks_v2_*.jsonl`만 Chroma에 넣는 것을 권장합니다. `source_store_v2_*.jsonl`은 임베딩 대상이 아니라 generation 단계에서 원문 확장과 근거 확인에 사용하는 파일입니다.

## 최종 정합성 점검 결과

2026-05-28 최종 로컬 검증 기준입니다.

| 점검 항목 | 결과 |
|---|---|
| 125/250/690 full validation | PASS |
| 125/250/690 slim validation | PASS |
| manifest hash와 실제 파일 hash | 일치 |
| duplicate `chunk_id` | 0건 |
| duplicate `source_store_id` | 0건 |
| missing `source_ref.source_store_id` | 0건 |
| slim 내 `embed_enabled=false` chunk | 0건 |
| slim 내 `toc` chunk | 0건 |
| 내부 작업용 문구(`alias 보강`, `alia보강`, `alis보강` 등) | 0건 |
| G2B 검증 rows의 공고번호 불일치 | 0건 |
| G2B 검증 rows의 입찰마감일 불일치 | 0건 |
| 사업기간 tail noise | 0건 |

## GitHub에 포함하지 않는 것

```text
data/original_data_list/
data/hwpx_664/
outputs/
Chroma DB
embedding cache
prediction JSONL
.env / API key
zip 파일
대용량 chunks/source_store JSONL
```

## 실행 메모

1. 원본 문서와 corpus 산출물은 공유 드라이브에서 받아 같은 경로 구조로 배치합니다.
2. corpus를 새로 만들거나 검증할 때는 `scripts/corpus/20260528/README.md`의 순서를 따릅니다.
3. retrieval/generation 실험은 slim `chunks_v2_*.jsonl`을 기준으로 Chroma collection을 만들고, 첫 build 후에는 collection을 재사용합니다.
