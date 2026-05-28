"""Phase 3 warning resolution 보조 함수 테스트."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_phase3_gold_sample_jsonl.py"
)


def load_script_module():
    """스크립트 파일을 테스트 모듈로 로드한다."""

    spec = importlib.util.spec_from_file_location("phase3_gold_builder", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_clean_submission_checklist_splits_and_removes_long_noise():
    module = load_script_module()

    values = [
        "제안서, 입찰서, 확인서, 경쟁입찰참가자격등록증, 실적증명서",
        "위 청렴계약이행서약은 상호신뢰를 바탕으로 한 약속으로써 반드시 지킬 것이며 계약해지 등 조치와 관련하여 손해배상을 청구하지 않습니다.",
    ]

    result = module.clean_submission_checklist(values)

    assert "제안서" in result
    assert "입찰서" in result
    assert all("손해배상" not in item for item in result)


def test_limited_evidence_ref_marks_source_doc_without_fake_chunk_id():
    module = load_script_module()

    result = module.make_limited_evidence_refs(["sample.hwp"])

    assert result == [
        {
            "source_file": "sample.hwp",
            "chunk_id": None,
            "fact_type": "",
            "evidence_summary": "source_docs 기준 근거 문서 확인. 세부 chunk 미확정",
        }
    ]
