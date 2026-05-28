"""Phase 4 LLM Judge API adapter 테스트."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from rag_eval.llm_judge_config import LLMJudgeSettings
from rag_eval.llm_judge_schema import JudgeInput


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def valid_output(case_id: str = "Q001") -> dict:
    subscore = {"score": 4, "label": "good", "rationale": "근거 범위 안에서 판단했습니다.", "evidence_refs": [0]}
    return {
        "id": case_id,
        "judge_overall_score": 4,
        "subscores": {
            "business_usefulness": dict(subscore),
            "completeness": dict(subscore),
            "groundedness": dict(subscore),
            "numeric_factuality": dict(subscore),
            "structure_clarity": dict(subscore),
            "risk_control": dict(subscore),
        },
        "risk_level": "low",
        "hallucination_risk": "low",
        "main_strengths": ["근거 기반"],
        "main_weaknesses": [],
        "unsupported_or_risky_claims": [],
        "needs_human_review": False,
        "judge_comment": "짧은 평가입니다.",
    }


class FakeResponse:
    def __init__(self, output_text: str | None = None, output_parsed: dict | None = None):
        self.output_text = output_text
        self.output_parsed = output_parsed


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeOpenAIClient:
    def __init__(self, outcomes):
        self.responses = FakeResponses(outcomes)


def judge_input() -> JudgeInput:
    return JudgeInput(
        id="Q001",
        question="제안서 제출 마감일은 언제입니까?",
        rag_answer="제안서 제출 마감일은 2025-05-01입니다.",
        source_docs=["A.hwp"],
        retrieved_evidence_summaries=[
            {"source_file": "A.hwp", "chunk_id": "c1", "evidence_summary": "제안서 제출 마감 일정 근거"}
        ],
    )


def settings(model: str = "gpt-test", api_key_present: bool = True) -> LLMJudgeSettings:
    return LLMJudgeSettings(
        provider="openai",
        model=model,
        api_key_present=api_key_present,
        api_key="test-secret-value" if api_key_present else "",
    )


def test_settings_repr_does_not_expose_api_key():
    value = repr(settings())

    assert "test-secret-value" not in value
    assert "api_key_present=True" in value


def test_openai_adapter_sends_structured_output_request_and_validates_response():
    from rag_eval.llm_judge_api import OpenAIJudgeAdapter

    client = FakeOpenAIClient([FakeResponse(output_text=json.dumps(valid_output()))])
    adapter = OpenAIJudgeAdapter(settings=settings(), client=client)

    result = adapter.evaluate(judge_input(), reference_mode="evidence_only")

    assert result["calculated_overall_score"] > 0
    assert result["structured_output_used"] is True
    assert result["fallback_json_mode_used"] is False
    assert result["retry_count"] == 0
    call = client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    user_payload = call["input"][1]["content"]
    assert "domain_gold_summary" not in user_payload
    assert "phase1_metrics" not in user_payload
    assert "test-secret-value" not in json.dumps(call, ensure_ascii=False)


def test_openai_adapter_retries_parse_error_once_and_succeeds():
    from rag_eval.llm_judge_api import OpenAIJudgeAdapter

    client = FakeOpenAIClient([FakeResponse(output_text="not json"), FakeResponse(output_text=json.dumps(valid_output()))])
    adapter = OpenAIJudgeAdapter(settings=settings(), client=client)

    result = adapter.evaluate(judge_input())

    assert result["parse_error"] is False
    assert result["retry_count"] == 1
    assert len(client.responses.calls) == 2


def test_openai_adapter_returns_validation_failure_after_retry():
    from rag_eval.llm_judge_api import OpenAIJudgeAdapter

    invalid = valid_output()
    invalid["judge_overall_score"] = 0
    client = FakeOpenAIClient([FakeResponse(output_text=json.dumps(invalid)), FakeResponse(output_text=json.dumps(invalid))])
    adapter = OpenAIJudgeAdapter(settings=settings(), client=client)

    result = adapter.evaluate(judge_input())

    assert result["validation_error"] is True
    assert result["needs_human_review"] is True
    assert result["calculated_overall_score"] == ""
    assert result["retry_count"] == 1


def test_openai_adapter_returns_timeout_failure_after_retry():
    from rag_eval.llm_judge_api import OpenAIJudgeAdapter

    client = FakeOpenAIClient([TimeoutError("slow"), TimeoutError("still slow")])
    adapter = OpenAIJudgeAdapter(settings=settings(), client=client)

    result = adapter.evaluate(judge_input())

    assert result["timeout_error"] is True
    assert result["error"]
    assert result["retry_count"] == 1
    assert "test-secret-value" not in json.dumps(result, ensure_ascii=False)


def test_openai_adapter_requires_key_and_model():
    from rag_eval.llm_judge_api import LLMJudgeAPIConfigurationError, OpenAIJudgeAdapter

    with pytest.raises(LLMJudgeAPIConfigurationError, match="API key"):
        OpenAIJudgeAdapter(settings=settings(api_key_present=False), client=FakeOpenAIClient([])).evaluate(judge_input())

    with pytest.raises(LLMJudgeAPIConfigurationError, match="model"):
        OpenAIJudgeAdapter(settings=settings(model=""), client=FakeOpenAIClient([])).evaluate(judge_input())


def test_runner_api_mode_uses_injected_client_and_writes_outputs(tmp_path):
    from rag_eval.llm_judge_runner import run_llm_judge_evaluation

    gold_path = tmp_path / "gold.jsonl"
    write_jsonl(
        gold_path,
        [
            {
                "id": "Q001",
                "source_set": "canonical_selected_50",
                "question": "제안서 제출 마감일은 언제입니까?",
                "task_family": "submission_eligibility_deadline",
                "question_type": "PHASE3",
                "difficulty": "중",
                "source_docs": ["A.hwp"],
                "can_use_for_phase3": True,
                "warning_resolution_status": "resolved",
                "submission_eligibility_deadline_gold": {"deadline": "2025-05-01"},
            }
        ],
    )
    predictions = pd.DataFrame(
        [
            {
                "id": "Q001",
                "question": "제안서 제출 마감일은 언제입니까?",
                "answer": "제안서 제출 마감일은 2025-05-01입니다.",
                "retrieved_contexts": [
                    {"rank": 1, "filename": "A.hwp", "chunk_id": "c1", "text": "제안서 제출 마감 일정 근거"}
                ],
            }
        ]
    )
    client = FakeOpenAIClient([FakeResponse(output_text=json.dumps(valid_output()))])

    result = run_llm_judge_evaluation(
        predictions_df=predictions,
        domain_gold_path=gold_path,
        output_dir=tmp_path / "out",
        experiment_meta={"experiment_id": "api", "experiment_name": "api", "run_datetime": "2026-05-27", "notes": ""},
        mode="api",
        settings=settings(),
        api_client=client,
    )

    assert result.summary["judged_count"] == 1
    assert result.summary["structured_output_used"] is True
    assert result.summary["api_key_present"] is True
    assert (tmp_path / "out" / "phase4_llm_judge_results.csv").exists()
    assert (tmp_path / "out" / "phase4_llm_judge_failure_cases.csv").exists()
    combined = "\n".join(path.read_text(encoding="utf-8-sig", errors="ignore") for path in (tmp_path / "out").glob("phase4_*"))
    assert "test-secret-value" not in combined
