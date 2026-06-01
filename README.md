# RAG Codeit Project

공공/기업 RFP 문서를 구조화하고, Chroma 기반 retrieval/generation 실험까지 재현하기 위한 프로젝트입니다. GitHub에는 코드, 노트북, 재현용 스크립트, 설명 문서만 포함하고 원본 문서와 생성 corpus 산출물은 포함하지 않습니다.

## 현재 기준

```text
parsing/corpus 생성   src/parsing/, notebooks/parsing/, scripts/corpus/20260528/, scripts/corpus/20260601/, scripts/g2b/
retrieval/generation  notebooks/rag/, src/generation/, docs/plans/, docs/notes/
```

- 데이터 생성 담당 범위는 HWP/HWPX 원문 처리, RFP 도메인 JSON key 설계, G2B 보강, slim corpus 생성, 정합성 검증입니다.
- 최신 corpus 생성/보정/검증 로직은 `scripts/corpus/20260528/`, `scripts/corpus/20260601/`, `scripts/g2b/`를 기준으로 확인합니다.
- retrieval/generation 실험은 `notebooks/rag/`와 `src/generation/`을 기준으로 확인합니다.
- 대용량 산출물은 별도 공유 드라이브에서 받아 로컬, Colab, GCP 런타임에 배치해서 사용합니다.

## Corpus 생성 흐름

1. 원본 HWP/PDF RFP를 준비하고, HWP는 HWPX로 변환해 표/문단 구조를 안정적으로 추출합니다. (664개 중 663개 문서 변환 성공)
2. 문서 본문과 표를 청킹하고, RFP 도메인 키워드 기반 `fact_candidates`를 생성합니다.
3. `project_budget`, `threshold_budget`, `reference_amount`, `base_amount`, `bid_deadline`, `project_duration`, `eligibility`, `requirements`처럼 숫자와 조건의 역할이 다른 key를 분리합니다.
4. 원문에 없는 필수 조달 정보는 나라장터에서 보강합니다. 대상은 사업예산금액, 입찰마감일, 공고번호입니다.
5. 125/250/690 corpus의 v2 schema를 맞추고, Chroma 적재용 slim corpus를 별도로 만듭니다.
6. Q201처럼 `2억원`이 평가/심사 기준인데 사업예산처럼 오인되는 케이스는 최종 단계에서 `780,230,000원` 사업예산과 분리합니다.
7. `final_corpus_audit_20260528.py`로 hash, 중복 id, source_ref, G2B 매칭, 내부 작업 문구 등을 확인합니다.

## 최종 Slim Corpus 기준

아래 값은 최종 로컬 산출물의 slim `chunks_v2_*.jsonl` raw 파일 크기 기준입니다. 

| corpus | slim chunks 파일 | chunks 수 | raw JSONL 크기 |
|---|---|---:|---:|
| 125 | `chunks_v2_125.jsonl` | 19,853 | 63.42 MiB |
| 250 | `chunks_v2_250.jsonl` | 36,945 | 125.53 MiB |
| 690 | `chunks_v2_690.jsonl` | 106,777 | 366.61 MiB |

실험용 embedding에는 slim corpus의 `chunks_v2_*.jsonl`만 Chroma에 넣으면 됩니다. `source_store_v2_*.jsonl`은 임베딩 대상이 아니라 generation 단계에서 원문 확장과 근거 확인에 사용하는 파일입니다.

## Retrieval 실험 기준

데이터 검증을 위한 retrieval 125 corpus exp100 기준 주요 결과는 다음과 같습니다.

| 조건 | 설명 | hit@5 | doc recall@5 | multi-doc recall@5 |
|---|---|---:|---:|---:|
| J0 dense | KoE5 dense baseline | 0.97 | 0.8958 | 0.7662 |
| J2 BM25 | BM25 keyword only | 0.92 | 0.8367 | 0.7130 |
| J3 RRF | dense + BM25 RRF | 0.99 | 0.9483 | 0.8843 |
| J5 hybrid | dense + BM25 RRF + reranker | 0.99 | 0.9725 | 0.9514 |

J5가 가장 안정적이지만 가장 느립니다. J3는 속도와 성능의 균형이 좋고, BM25는 단독 성능은 낮지만 숫자, 기관명, 공고명처럼 표면 단어가 중요한 질문에서 보완 역할을 합니다.

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
개인 회의용 HTML/대본
```

## 실행 메모

1. 원본 문서와 corpus 산출물은 공유 드라이브에서 받아 같은 경로 구조로 배치합니다.
2. corpus를 새로 만들거나 검증할 때는 `scripts/corpus/20260528/README.md`의 순서를 따릅니다.
3. 2026-06-01 이후 Q201 CMS 예산 guard까지 반영하려면 `scripts/corpus/20260601/apply_q201_cms_budget_guard_20260601.py --project-root . --apply`를 실행한 뒤 audit을 다시 실행합니다.
4. 수정된 corpus를 사용하면 기존 Chroma collection은 재사용하지 말고 다시 생성해야 합니다.
