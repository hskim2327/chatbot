# Phase 3 Gold Warning Resolution Report

## 1. 작업 목적

최종 Phase 3 gold set의 warning 14개를 해결 가능한 범위에서 보완하고, 남는 warning은 accepted_warning으로 명확히 분류했다.

## 2. 입력 파일 목록

- `eval/evaluation/data/rfp_domain_gold_sample.jsonl`
- `eval/evaluation/data/rfp_domain_gold_sample.xlsx`
- `eval/evaluation/data/rfp_domain_gold_sample_readable.csv`
- `eval/evaluation/data/rfp_domain_gold_sample_validation.csv`
- `new_data/chunks_v2_690.jsonl`
- `data/eval/eval_batch_01.csv` ~ `eval_batch_25.csv`

## 3. 기존 warning 14개 요약

- `Q067`
- `Q068`
- `Q069`
- `Q071`
- `Q072`
- `Q025`
- `Q042`
- `Q395`
- `P3-SUB-001`
- `P3-SUB-004`
- `P3-SUB-010`
- `Q019`
- `Q020`
- `Q039`

## 4. warning 유형별 처리 전략

- evidence_refs 없음: chunks_v2에서 source_file 기준 근거 chunk를 찾고, 실패 시 limited evidence_ref로 accepted_warning 처리
- noisy candidate: 제출서류 checklist만 남기고 긴 안내/계약 일반 문구 제거
- question rewrite: 질문 의미와 gold block 범위를 유지하면서 자연스럽게 수정
- robust 원 질문 id 없음: canonical eval에서 같은 source_docs와 유사 의도 질문을 찾고, 불명확하면 accepted_warning 처리

## 5. resolved 문항 목록

- `Q067`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q068`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q069`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q071`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q072`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q025`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q042`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `Q395`: new_data/chunks_v2_690.jsonl에서 source_file 기준 fact/text chunk 근거를 보완함
- `P3-SUB-001`: 질문 의도에 맞춰 제출서류 checklist만 남기고 noisy eligibility 문구를 제거함
- `P3-SUB-004`: 입찰참가자격 중심으로 질문 문장을 자연스럽게 수정함
- `P3-SUB-010`: gold block에 실제 포함된 제출서류/입찰참가자격/마감일 범위로 질문을 좁힘
- `Q019`: canonical eval에서 같은 source_docs와 유사 의도를 가진 원 질문 후보 Q062를 연결함
- `Q020`: canonical eval에서 같은 source_docs와 유사 의도를 가진 원 질문 후보 Q084를 연결함

## 6. accepted_warning 문항 목록

- `Q039`: 신뢰도 높은 원 질문 id를 확정하지 못했으나 same source/key field 기준 robust 평가가 가능함


## 7. unresolved_needs_fix 문항 목록

- 없음

## 8. evidence_refs 보완 결과

evidence_refs가 비어 있던 문항은 chunks_v2 검색 또는 limited evidence_ref 방식으로 보완했다.

## 9. P3-SUB-001 noisy candidate 처리 결과

제출서류 checklist만 남기고, 질문 의도와 직접 관련이 낮은 긴 eligibility/계약 일반 문구는 제거했다.

## 10. P3-SUB-004/P3-SUB-010 question rewrite 결과

- `P3-SUB-004`: 입찰참가자격 중심 질문으로 수정
- `P3-SUB-010`: 제출서류, 입찰참가자격, 입찰마감일 범위로 수정

## 11. Q019/Q020/Q039 robust 연결 id 처리 결과

canonical eval에서 같은 source_docs와 유사 의도 질문 후보를 탐색했다. 신뢰 가능한 경우 related_original_id를 채웠고, 불명확한 경우에는 same source/key field 기준으로 accepted_warning 처리한다.

## 12. 최종 gold_generation_status 분포

- `complete`: 49
- `complete_with_warnings`: 1

## 13. can_use_for_phase3=false 문항 목록

- 없음

## 14. 정답지 사용 가능성 판단

unresolved_needs_fix가 없고 can_use_for_phase3=false 문항이 없으므로 Phase 3 metric 구현 단계로 넘어갈 수 있다. accepted_warning 문항은 보고서에서 주의사항으로 표시하면 된다.

## 15. 아직 남은 리스크

- `Q039`: related_original_id 미확정이나 same source/key field 기준으로 평가 가능


## 16. 다음 단계 제안

Phase 3 metric 구현 시 `warning_resolution_status`를 결과 리포트에 함께 표시하고, accepted_warning 문항은 평가 제외가 아니라 해석 주의 문항으로 다룬다.

## resolution status 분포

- `resolved`: 13
- `accepted_warning`: 1