# 평가 결과 웹 대시보드 설계 문서

## 1. 문서 목적

이 문서는 RAG 평가 모듈의 Phase 1~4 실행 결과를 팀원이 웹에서 확인할 수 있도록 수집, 저장, 시각화하는 대시보드 설계안이다. 현재 평가 로직은 `eval/evaluation/scripts/run_evaluation.py`와 `eval/evaluation/src/rag_eval/`에 구현되어 있으며, 실제 RAG pipeline 결합 후 팀원들이 각자 평가를 실행할 예정이다.

이번 문서는 웹사이트 구현 문서가 아니라 구현 전 설계 문서다. 평가 로직을 바꾸지 않고, 평가 결과 파일을 안전하게 업로드해 실험 목록, 실험 상세, Phase별 점수, 실패 케이스, 실험 비교를 볼 수 있는 구조를 제안한다.

대시보드는 평가 로직을 대체하지 않는다. 점수 계산은 계속 로컬 평가 모듈에서 수행하고, 웹사이트는 결과를 수집하고 시각화하는 역할만 맡는다.

보안상 실제 OpenAI API key, dashboard token, `.env` 내용, 원본 RFP 전문, 긴 table, source_store 전체는 웹사이트로 전송하지 않는다.

## 2. 설계 목표

- 팀원들이 각자 RAG predictions를 생성하고 평가를 실행한다.
- 평가 결과는 먼저 로컬 `eval/evaluation/outputs/eval/`에 저장된다.
- 평가가 끝나면 결과 파일과 manifest를 bundle로 묶어 Dashboard Upload API로 자동 전송한다.
- 웹사이트에서는 실험 목록, 실험 상세, Phase별 점수, 실패 케이스, 실험 비교를 확인한다.
- 자동전송은 선택 기능이다. `--upload-results`를 명시하지 않으면 업로드하지 않는다.
- 업로드 실패가 로컬 평가 결과 저장을 막지 않는다.
- secret, 원본 RFP 전문, 긴 context는 업로드하지 않는다.

## 3. 전체 아키텍처

```text
RAG predictions
  ↓
run_evaluation.py
  ↓
Phase 1/2/3/4 results
  ↓
experiment_manifest.json 생성
  ↓
결과 파일 bundle 생성
  ↓
Dashboard Upload API
  ↓
Backend 파싱/저장
  ↓
Database + Artifact Storage
  ↓
Web Dashboard
```

세부 흐름은 다음과 같다.

1. 팀원이 RAG pipeline으로 `predictions.jsonl`을 생성한다.
2. `run_evaluation.py`로 Phase 1~4 평가를 실행한다.
3. 결과 파일이 `eval/evaluation/outputs/eval/`에 저장된다.
4. 평가 모듈이 `experiment_manifest.json`을 생성한다.
5. 업로드 대상 결과 파일을 bundle로 묶는다.
6. `--upload-results`가 켜져 있으면 Dashboard Upload API로 전송한다.
7. Backend는 manifest와 artifact를 검증하고 저장한다.
8. Web Dashboard는 DB와 artifact storage에서 실험 결과를 조회해 보여준다.

## 4. 자동전송 CLI 옵션 설계

나중에 `run_evaluation.py`와 runner에 다음 옵션을 추가하는 것을 제안한다.

| 옵션 | 의미 |
|---|---|
| `--upload-results` | 평가 종료 후 dashboard 서버로 결과를 업로드한다. 없으면 업로드하지 않는다. |
| `--dashboard-url` | Dashboard Upload API base URL이다. |
| `--dashboard-api-token` | 업로드 인증 token이다. 직접 값 입력보다 환경변수 사용을 권장한다. |
| `--experiment-name` | 웹에서 표시할 실험명이다. |
| `--experiment-owner` | 실행자 또는 팀원 이름/ID다. |
| `--experiment-tags` | 쉼표 구분 태그다. 예: `baseline,hybrid50,reranker-v2` |
| `--experiment-notes` | 실험 메모다. |
| `--upload-artifacts` | 기본 summary 외 상세 artifact까지 업로드할지 제어한다. |
| `--upload-timeout-seconds` | 업로드 timeout 설정이다. |

정책:

- `--upload-results`가 없으면 자동전송하지 않는다.
- dashboard token은 OS 환경변수 또는 `.env`에서 읽는 방식을 기본으로 한다.
- token 값은 로그, manifest, 결과 파일, experiment log에 저장하지 않는다.
- 업로드 실패는 warning으로 남기고 로컬 평가 결과는 유지한다.
- strict upload mode는 추후 `--require-upload` 같은 별도 옵션으로 둘 수 있다.

## 5. experiment_manifest.json 설계

`experiment_manifest.json`은 대시보드가 실험을 이해하기 위한 최소 메타데이터다. 로컬 전체 경로는 저장하지 않고 basename 또는 상대 논리명만 저장한다.

예시 schema:

```json
{
  "run_id": "20260529-103000-team-a-baseline",
  "experiment_name": "baseline-rag-v1",
  "experiment_owner": "team-a",
  "created_at": "2026-05-29T10:30:00+09:00",
  "git_commit": null,
  "branch": null,
  "predictions_path_name_only": "predictions.jsonl",
  "enabled_phases": ["phase1", "phase3", "phase4"],
  "phase1_enabled": true,
  "phase2_enabled": false,
  "phase3_enabled": true,
  "phase4_enabled": true,
  "judge_model": "model-name-from-config",
  "judge_reference_mode": "evidence_only",
  "judge_mode": "api",
  "prompt_version": "phase4_judge_v1",
  "schema_version": "phase4_judge_schema_v1",
  "rag_pipeline_version": null,
  "retriever_version": null,
  "generator_model": null,
  "notes": "baseline run after retrieval update",
  "tags": ["baseline", "phase4"],
  "artifact_files": [
    "eval_summary.md",
    "eval_results.csv",
    "phase3_domain_summary.md",
    "phase3_domain_results.csv",
    "phase4_llm_judge_summary.md",
    "phase4_llm_judge_results.csv"
  ],
  "security_redaction_applied": true
}
```

금지:

- `OPENAI_API_KEY`, dashboard token, `.env` 내용 저장 금지
- 로컬 전체 경로 저장 금지
- 원본 RFP 전문 또는 source_store 전체 저장 금지

## 6. 업로드 대상 파일 설계

### 필수 후보

| 파일 | 용도 |
|---|---|
| `experiment_manifest.json` | 실험 메타데이터와 업로드 대상 목록 |
| `eval_summary.md` | Phase 1 검색 성능 요약 |
| `eval_results.csv` | Phase 1 문항별 검색 결과 |
| `phase3_domain_summary.md` | Phase 3 한글 요약과 종합 판정 |
| `phase3_domain_results.csv` | Phase 3 문항별 점수와 한글 보조 컬럼 |
| `phase3_domain_failure_cases.csv` | Phase 3 실패 케이스와 한글 개선 힌트 |
| `phase4_llm_judge_summary.md` | Phase 4 전체 총평, 점수, 레이턴시 |
| `phase4_llm_judge_results.csv` | Phase 4 문항별 Judge 결과와 한글 총평 |
| `phase4_llm_judge_failure_cases.csv` | Phase 4 실패 케이스 |
| `experiment_logs/phase4_llm_judge_experiments.csv` 일부 또는 마지막 row | Phase 4 실험 메타 비교 |

### 선택 후보

| 파일 | 정책 |
|---|---|
| `phase4_llm_judge_inputs.jsonl` | question, answer, evidence summary가 포함될 수 있으므로 선택 업로드로 둔다. 업로드 전 redaction 검사 필요 |
| `phase3_domain_results.json` | nested 분석이 필요할 때만 업로드 |
| `phase4_llm_judge_results.json` | nested Judge output 분석이 필요할 때만 업로드 |

업로드 금지:

- `.env`
- API key나 token이 들어간 파일
- source_store 전체
- 원본 RFP 전문
- 긴 chunk text 또는 긴 table
- 개발용 cache, pytest cache, pycache

## 7. Backend API 설계

FastAPI 기준 endpoint 설계다.

### POST `/api/runs`

실험 manifest를 등록한다.

Request:

```json
{
  "run_id": "20260529-103000-team-a-baseline",
  "experiment_name": "baseline-rag-v1",
  "experiment_owner": "team-a",
  "created_at": "2026-05-29T10:30:00+09:00",
  "enabled_phases": ["phase1", "phase3", "phase4"],
  "tags": ["baseline"],
  "notes": "baseline run",
  "security_redaction_applied": true
}
```

Response:

```json
{
  "run_id": "20260529-103000-team-a-baseline",
  "status": "registered",
  "artifact_upload_url": "/api/runs/20260529-103000-team-a-baseline/artifacts"
}
```

### POST `/api/runs/{run_id}/artifacts`

결과 파일을 업로드한다. multipart upload를 기본으로 한다.

Request:

- `file`: 업로드 파일
- `filename`: basename
- `file_type`: `csv | md | json | jsonl`
- `checksum`: SHA-256 등

Response:

```json
{
  "run_id": "20260529-103000-team-a-baseline",
  "filename": "phase4_llm_judge_results.csv",
  "status": "stored"
}
```

### POST `/api/runs/{run_id}/complete`

업로드 완료 처리와 파싱 작업을 시작한다.

Request:

```json
{
  "artifact_count": 8
}
```

Response:

```json
{
  "run_id": "20260529-103000-team-a-baseline",
  "status": "parsed"
}
```

### GET `/api/runs`

실험 목록을 조회한다.

Response:

```json
{
  "runs": [
    {
      "run_id": "20260529-103000-team-a-baseline",
      "experiment_name": "baseline-rag-v1",
      "owner": "team-a",
      "created_at": "2026-05-29T10:30:00+09:00",
      "phase3_score": 0.72,
      "phase4_score_100": 68.5,
      "overall_label_ko": "제한적 참고 가능",
      "failure_count": 12
    }
  ]
}
```

### GET `/api/runs/{run_id}`

실험 상세 메타데이터와 전체 요약을 조회한다.

### GET `/api/runs/{run_id}/phase3`

Phase 3 summary, task별 점수, failure cases를 조회한다.

### GET `/api/runs/{run_id}/phase4`

Phase 4 summary, 문항별 한글 총평, 레이턴시, human review 필요 문항을 조회한다.

### GET `/api/runs/{run_id}/failures`

Phase 1/3/4 실패 케이스를 통합 조회한다.

Query parameters:

- `phase`
- `task_family`
- `severity`
- `needs_human_review`
- `score_min`
- `score_max`

### GET `/api/compare?base_run_id=...&target_run_id=...`

두 실험을 비교한다.

Response:

```json
{
  "base_run_id": "baseline",
  "target_run_id": "reranker-v2",
  "phase3_score_delta": 0.04,
  "phase4_score_100_delta": 6.2,
  "failure_count_delta": -5,
  "latency_delta_sec": 1.8,
  "improved_items": ["budget", "groundedness"],
  "regressed_items": ["latency"]
}
```

## 8. DB schema 설계

SQLite로 MVP를 시작하고, 팀 배포 시 PostgreSQL 또는 Supabase로 확장할 수 있다.

### `evaluation_runs`

| 컬럼 | 설명 |
|---|---|
| `id` | 내부 PK |
| `run_id` | 실험 고유 ID |
| `experiment_name` | 실험명 |
| `owner` | 실행자 |
| `created_at` | 로컬 평가 생성 시각 |
| `uploaded_at` | 서버 업로드 시각 |
| `enabled_phases` | 실행 Phase 목록 |
| `judge_model` | Phase 4 Judge 모델 |
| `judge_reference_mode` | `evidence_only` 또는 `gold_guided` |
| `prompt_version` | Judge prompt version |
| `schema_version` | Judge schema version |
| `tags` | 태그 JSON |
| `notes` | 실험 메모 |
| `status` | `registered`, `uploading`, `parsed`, `failed` |

### `phase1_summary`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `hit_at_5` | Top-5 정답 문서 포함률 |
| `mrr_at_5` | 첫 정답 문서 순위 점수 |
| `ndcg_at_5` | 정답 문서 순위 품질 |
| `evaluated_count` | 평가 문항 수 |

### `phase3_summary`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `evaluated_count` | 평가 문항 수 |
| `failure_count` | 실패 문항 수 |
| `average_phase3_task_score` | Phase 3 대표 점수 평균 |
| `summary_text_ko` | summary.md의 한글 요약 텍스트 |

### `phase4_summary`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `evaluated_count` | 평가 문항 수 |
| `failure_count` | 실패 문항 수 |
| `overall_score` | 1~5 기준 종합 점수 |
| `overall_score_100` | 100점 환산 |
| `overall_label_ko` | 한글 판정 |
| `average_latency_sec` | 평균 답변 생성 시간 |
| `summary_text_ko` | 전체 평가 총평 |
| `judge_model` | Judge 모델 |

### `phase4_cases`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `question_id` | 문항 ID |
| `question` | 질문 |
| `answer` | 생성 답변 |
| `calculated_overall_score` | 코드 후처리 종합 점수 |
| `overall_label` | 한글 판정 |
| `case_evaluation_ko` | 문항별 한글 총평 |
| `strengths_ko` | 주요 강점 |
| `weaknesses_ko` | 주요 약점 |
| `improvement_hint_ko` | 개선 힌트 |
| `risk_comment_ko` | 실무 위험 설명 |
| `answer_latency_sec` | 답변 생성 시간 |
| `needs_human_review` | 사람이 확인해야 하는지 여부 |

### `failure_cases`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `phase` | 실패가 발생한 Phase |
| `question_id` | 문항 ID |
| `question` | 질문 |
| `failure_reason_ko` | 한글 실패 사유 |
| `major_penalty_items` | 주요 감점 항목 |
| `improvement_hint_ko` | 개선 힌트 |
| `severity` | `low`, `medium`, `high` |

### `artifacts`

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실험 ID |
| `filename` | 업로드 파일명 |
| `file_type` | 확장자/파일 유형 |
| `storage_path` | artifact 저장 위치 |
| `uploaded_at` | 업로드 시각 |
| `checksum` | 파일 무결성 확인값 |

## 9. Frontend 화면 설계

### 9-1. 실험 목록 화면

표시 항목:

- 실험명
- 실행자
- 실행일
- Phase 3 점수
- Phase 4 종합 점수
- 전체 판정
- 실패 문항 수
- 평균 응답 시간
- Judge 모델
- 태그

주요 기능:

- 상단 카드: 전체 실험 수, 최근 Phase 4 평균 점수, 실패 문항 수, 평균 레이턴시
- 메인 표: 실험명, 실행자, 실행일, Phase별 점수, 전체 판정, 실패 문항 수, 모델, 태그
- 점수 badge: `우수`, `적합`, `제한적 참고`, `부적합` 같은 한글 라벨
- 차트: 최근 run의 Phase 3/4 점수 추이 line chart
- 최신 실행순 정렬
- 태그/실행자/모델 필터
- baseline 지정 표시
- 상세 화면 이동

### 9-2. 실험 상세 화면

표시 항목:

- 실험 메타데이터
- 실행 Phase
- Phase 1 검색 성능
- Phase 3 도메인 평가 요약
- Phase 4 LLM Judge 요약
- 전체 평가 총평
- 주요 개선 우선순위
- 업로드 artifact 목록

구성:

- 상단 핵심 정보 카드: Phase 3 대표 점수, Phase 4 종합 점수, 실패 케이스 수, 평균 응답 시간
- 좌측 본문: Phase별 summary markdown 요약
- 우측 패널: 주요 실패 케이스 top 5와 human review 필요 문항
- 하단 차트: Phase 4 subscore bar chart, risk_level 분포 도넛 차트

### 9-3. Phase 3 상세 화면

표시 항목:

- task_family별 점수
- 실패 케이스
- 한글 실패 사유
- 주요 감점 항목
- 개선 힌트

해석 포인트:

- 검색 성능과 답변 내용 품질을 분리해서 보여준다.
- Phase 3는 gold block 기반 deterministic 평가라는 점을 화면 안내로 표시한다.

구성:

- task_family별 점수 카드: budget, required_fields, submission_eligibility_deadline, unanswerable, multi_doc_comparison, robust_query_type_e
- task별 평균 table: 내부 metric명과 한글 표시명을 함께 표시
- 실패 케이스 table: 한글 실패 사유, 주요 감점 항목, 개선 힌트 컬럼 고정
- 필터: task_family, 점수 구간, warning 여부, 실패 사유

### 9-4. Phase 4 상세 화면

표시 항목:

- 종합 점수
- 100점 환산
- 전체 판정
- 항목별 평균 점수
- 문항별 한글 총평
- 주요 강점/약점
- 레이턴시
- `needs_human_review`

구성:

- 종합 점수 카드: 원점수, 100점 환산, 한글 판정
- subscore bar chart: business_usefulness, completeness, groundedness, numeric_factuality, structure_clarity, risk_control
- risk 도넛 차트: `risk_level`, `hallucination_risk`
- 문항별 table: question_id, 종합 점수, 한글 총평, 개선 힌트, 레이턴시
- 우측 상세 패널: table row 클릭 시 질문, 답변, 한글 총평, 강점/약점, 위험 설명 표시

### 9-5. 실패 케이스 화면

필터:

- phase
- task_family
- severity
- needs_human_review
- 점수 구간
- 실패 유형

표시 항목:

- 질문 ID
- 질문
- 실패 사유 한글 요약
- 주요 감점 항목
- 개선 힌트
- 관련 점수

구성:

- 왼쪽 필터 영역: phase, task_family, severity, 점수 구간
- 중앙 실패 케이스 table: 실패 사유 한글 요약과 개선 힌트를 우선 노출
- 오른쪽 상세 패널: 선택한 실패 케이스의 질문, 답변, 관련 metric, 실무 위험 설명
- 차트: 실패 유형 도넛 차트, task_family별 실패 count bar chart

### 9-6. 실험 비교 화면

기능:

- baseline run 선택
- target run 선택
- Phase 3/4 점수 차이 표시
- 실패 문항 수 변화
- 레이턴시 변화
- 개선/악화 항목 표시
- 같은 question_id 기준 case-level 변화 표시

구성:

- baseline/target 선택 control
- score delta 카드: Phase 3, Phase 4, 실패 수, 레이턴시 변화
- 추이 차트: 여러 run을 시간순으로 비교
- 개선/악화 table: question_id 기준 점수 변화와 실패 사유 변화

## 10. UI/UX 디자인 원칙

대시보드는 평가 실험을 반복해서 확인하는 운영 도구다. 따라서 마케팅 페이지처럼 장식적인 구성이 아니라, 숫자와 실패 원인을 빠르게 훑어볼 수 있는 조밀한 분석 UI를 목표로 한다.

### 10-1. 기본 레이아웃

- 왼쪽 사이드바를 고정한다.
  - 메뉴: `실험 목록`, `실험 상세`, `Phase 3`, `Phase 4`, `실패 케이스`, `실험 비교`, `Artifacts`
  - 현재 선택한 run과 baseline run을 사이드바 하단에 표시한다.
- 상단에는 핵심 정보 카드 4~6개를 배치한다.
  - Phase 3 대표 점수
  - Phase 4 종합 점수
  - 전체 판정
  - 실패 문항 수
  - 평균 응답 시간
  - Judge 모델
- 본문은 table과 chart 중심으로 구성한다.
- 오른쪽에는 실패 케이스 상세 패널을 둘 수 있다. row 클릭 시 질문, 답변, 실패 사유, 개선 힌트를 즉시 확인하게 한다.

### 10-2. 화면 구성 요소

| 구성 요소 | 용도 |
|---|---|
| 핵심 정보 카드 | 실험의 현재 상태를 5초 안에 파악 |
| 실험 목록 테이블 | run 간 비교와 상세 진입 |
| 점수 추이 차트 | baseline 대비 개선/악화 추세 확인 |
| 실패 유형 도넛 차트 | 실패 원인의 비중 확인 |
| task별 bar chart | Phase 3 task_family별 취약점 확인 |
| subscore radar/bar chart | Phase 4 세부 품질 확인 |
| 오른쪽 상세 패널 | 실패 케이스 drill-down |

### 10-3. 색상 기준

점수 색상은 일관되게 사용한다.

| 100점 환산 | 라벨 | 색상 의미 |
|---:|---|---|
| 85~100 | 실무 사용 매우 적합 | 초록 |
| 70~84 | 실무 사용 적합 | 연두/청록 |
| 55~69 | 제한적 참고 가능 | 노랑 |
| 40~54 | 실무 사용 부적합에 가까움 | 주황 |
| 0~39 | 실무 사용 부적합 | 빨강 |

추가 규칙:

- `needs_human_review=True`는 보라색 또는 진한 주황 badge로 표시한다.
- `risk_level=high`와 `hallucination_risk=high`는 빨강 badge로 표시한다.
- latency는 점수 색상과 분리하고 회색/파랑 계열로 표시한다.

### 10-4. 점수 라벨 기준

- Phase 1은 `hit_at_5`, `mrr_at_5`, `ndcg_at_5`를 0~1 기준과 100점 환산을 함께 보여준다.
- Phase 3는 `phase3_task_score`와 task별 metric을 0~1 기준으로 보여준다.
- Phase 4는 `calculated_overall_score`를 공식 종합 점수로 보여주고, 100점 환산을 함께 표시한다.
- `judge_overall_score`는 참고값으로만 표시한다.

### 10-5. 반응형 레이아웃

- 데스크톱: 사이드바 + 본문 2열 + 오른쪽 상세 패널 구조를 사용한다.
- 태블릿: 사이드바를 접고, 상세 패널은 drawer로 전환한다.
- 모바일: 핵심 카드와 table 요약만 우선 표시하고, chart는 접을 수 있게 한다.
- table은 가로 scroll을 허용하되, `experiment_name`, `run_id`, `overall_label`, `failure_count`는 고정 컬럼으로 둔다.

### 10-6. 사용성 원칙

- 영어 내부 컬럼명은 tooltip이나 보조 텍스트로 보여주고, 기본 표시는 한글 표시명을 우선한다.
- 실패 케이스는 “왜 낮은가”와 “무엇을 고치면 되는가”를 먼저 보여준다.
- raw artifact 다운로드는 제공하되, 기본 화면에는 긴 JSON/CSV 원문을 그대로 노출하지 않는다.
- 비교 화면에서는 절대 점수보다 delta와 실패 수 변화가 눈에 띄게 한다.

## 11. MVP 범위

### MVP v0

- 결과 자동 업로드 API
- `experiment_manifest.json` 저장
- summary CSV/MD 파싱
- 실험 목록 화면
- 실험 상세 화면
- Phase 4 failure cases 표시
- 실험 비교는 단순 점수 차이만 제공

### v1

- Phase 3/4 상세 필터
- 실패 유형 통계
- 태그/노트 편집
- baseline 지정
- run 비교 차트

### v2

- 팀원별 권한
- 자동 알림
- Git commit 연동
- RAG pipeline version 추적
- 대시보드 배포
- Supabase/PostgreSQL 전환

## 12. 보안 설계

필수 정책:

- API key는 업로드하지 않는다.
- `.env`는 업로드하지 않는다.
- 원본 RFP 전문은 업로드하지 않는다.
- 긴 chunk text와 긴 table은 업로드하지 않는다.
- source_store 전체 업로드는 금지한다.
- evidence summary만 업로드하는 것을 기본으로 한다.
- upload token은 `.env` 또는 OS 환경변수에서 읽는다.
- dashboard api token은 로그, manifest, 결과 파일에 남기지 않는다.
- 업로드 파일 크기를 제한한다.
- 허용 확장자는 `csv`, `json`, `jsonl`, `md`로 제한한다.
- secret-like pattern 검사를 업로드 전 수행한다.
- 로컬 전체 경로는 제거하고 basename만 manifest에 저장한다.

업로드 전 검사 후보:

- `OPENAI_API_KEY`
- `DASHBOARD_API_TOKEN`
- `sk-` 형태의 secret-like pattern
- `.env` 파일명
- 긴 원문 context 길이 초과
- 허용 확장자 외 파일

## 13. 결과 파싱 설계

Dashboard backend는 업로드된 파일에서 다음 값을 읽는다.

| 파일 | 읽는 값 |
|---|---|
| `eval_summary.md` | Phase 1 검색 성능 요약 |
| `eval_results.csv` | 문항별 retrieval metric |
| `phase3_domain_summary.md` | 검색/답변/예산 평가 요약, 종합 판정 |
| `phase3_domain_results.csv` | task별 점수, 한글 보조 컬럼 |
| `phase3_domain_failure_cases.csv` | 한글 실패 사유, 주요 감점 항목, 개선 힌트 |
| `phase4_llm_judge_summary.md` | 종합 점수, 전체 판정, 전체 평가 총평, 평균 레이턴시 |
| `phase4_llm_judge_results.csv` | 문항별 점수, 문항별 한글 총평, 개선 힌트, 레이턴시 |
| `phase4_llm_judge_failure_cases.csv` | 실패 사유 한글 요약, 주요 감점 항목, 실무 위험 설명 |
| `experiment_logs/phase4_llm_judge_experiments.csv` | model, prompt/schema version, judged_count, error count |

파싱 우선순위:

1. CSV에서 구조화된 numeric 값을 우선 읽는다.
2. Markdown summary는 한글 설명과 총평 표시용으로 저장한다.
3. JSON 파일은 nested detail이 필요할 때 보조로 사용한다.

## 14. 평가 모듈 쪽 변경 계획

나중에 평가 모듈에 추가할 파일 후보:

| 파일 | 책임 |
|---|---|
| `eval/evaluation/src/rag_eval/dashboard_upload_config.py` | dashboard URL, token 존재 여부, timeout, 업로드 정책 로드 |
| `eval/evaluation/src/rag_eval/dashboard_upload_client.py` | manifest 등록, artifact 업로드, complete 호출 |
| `eval/evaluation/src/rag_eval/experiment_manifest.py` | manifest 생성, artifact 목록 수집, basename 처리 |
| `eval/evaluation/tests/test_dashboard_upload_client.py` | 업로드 client mock 테스트 |
| `eval/evaluation/tests/test_experiment_manifest.py` | manifest schema와 redaction 테스트 |

추가할 CLI 옵션 후보:

- `--upload-results`
- `--dashboard-url`
- `--dashboard-api-token-env`
- `--experiment-owner`
- `--experiment-tags`
- `--experiment-notes`
- `--upload-artifacts`
- `--upload-timeout-seconds`

이번 문서 단계에서는 구현하지 않는다.

## 15. 웹 앱 프로젝트 구조 제안

추천 위치는 프로젝트 루트의 `dashboard/`다.

이유:

- 평가 모듈 `eval/evaluation/`은 평가 로직과 테스트 중심으로 유지하는 것이 좋다.
- dashboard는 backend/frontend/storage를 포함하는 별도 application이 될 가능성이 높다.
- 루트 `dashboard/`가 있으면 배포, 의존성, README, Docker 구성을 평가 모듈과 분리하기 쉽다.

추천 구조:

```text
dashboard/
  backend/
    app/
      main.py
      routers/
      models/
      services/
      storage/
    tests/
  frontend/
    ...
  README.md
```

Streamlit MVP로 시작한다면:

```text
dashboard/
  streamlit_app.py
  services/
  README.md
```

다만 자동전송 API가 목표라면 Streamlit만으로는 부족하므로 FastAPI backend는 유지하는 편이 낫다.

## 16. 기술 스택 비교와 추천

### Streamlit MVP

장점:

- 빠르게 만들 수 있다.
- Python만으로 구현 가능하다.
- CSV/Markdown 파싱과 내부 팀용 화면에 적합하다.

단점:

- 인증/권한/확장성이 약하다.
- 자동 업로드 API를 별도로 붙여야 한다.

### FastAPI + SQLite/PostgreSQL + 간단한 UI

장점:

- 자동전송 API에 적합하다.
- backend 파싱/저장/보안 검사를 구조화하기 좋다.
- SQLite로 시작해 PostgreSQL로 확장할 수 있다.

단점:

- Streamlit보다 초기 구현량이 많다.

### FastAPI + Supabase + Next.js

장점:

- 팀 대시보드로 확장하기 좋다.
- 인증, 권한, 배포, DB 관리가 체계적이다.
- 프론트엔드 분리와 차트 UI 확장이 쉽다.

단점:

- 초기 복잡도가 높다.
- 평가 모듈 작업과 별도의 웹 개발 범위가 커진다.

최종 추천:

- 자동전송을 목표로 하므로 FastAPI backend는 필요하다.
- 이미지 시안처럼 polished dashboard UI를 원하면 `FastAPI + SQLite/PostgreSQL + Next.js + Tailwind + shadcn/ui + Recharts`를 추천한다.
- 가장 균형 잡힌 MVP는 `FastAPI + SQLite + Next.js`다. 자동 업로드 API와 대시보드 UI를 분리하면서도 PostgreSQL/Supabase로 확장하기 쉽다.
- 팀이 빠른 내부 검증을 더 중시하면 `FastAPI upload API + Streamlit admin view`도 현실적인 절충안이다.
- 이후 사용량과 배포 필요성이 커지면 Supabase/PostgreSQL과 Next.js로 확장한다.

## 17. 구현 단계 로드맵

1. Dashboard 설계 문서를 팀에서 확정한다.
2. `experiment_manifest.json` 생성 로직을 평가 모듈에 추가한다.
3. dashboard upload client를 구현한다.
4. FastAPI upload API MVP를 구현한다.
5. SQLite 저장 구조를 만든다.
6. 실험 목록/상세 화면을 구현한다.
7. 실패 케이스 화면을 구현한다.
8. 실험 비교 화면을 구현한다.
9. 업로드 token, 파일 크기 제한, secret-like pattern 검사 등 보안 장치를 추가한다.
10. 팀원 1명과 end-to-end 업로드 테스트를 수행한다.
11. 전체 팀에 적용한다.

## 18. 구현하지 않는 범위

이번 단계에서 하지 않는 것:

- 웹사이트 구현
- 평가 모듈 코드 수정
- 실제 upload API 호출
- 실제 서버 생성
- 실제 `.env` 생성
- API key 또는 dashboard token 작성
- 원본 RFP 전문 업로드 설계
- source_store 전체 업로드 설계

## 19. 남은 결정 사항

- MVP UI를 server-rendered HTML로 할지, Streamlit admin view로 할지 결정해야 한다.
- dashboard 저장소를 이 repo 안의 `dashboard/`로 둘지 별도 repo로 분리할지 결정해야 한다.
- 팀원 인증이 필요한지, 내부 network만으로 충분한지 결정해야 한다.
- artifact 보존 기간과 삭제 정책이 필요하다.
- `phase4_llm_judge_inputs.jsonl`을 업로드할지 여부는 보안 검토 후 결정해야 한다.
