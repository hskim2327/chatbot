"""Phase 4 LLM Judge OpenAI API adapter."""

from __future__ import annotations

import json
from typing import Any

from .llm_judge_config import LLMJudgeSettings
from .llm_judge_prompt import build_judge_case_payload, build_system_prompt
from .llm_judge_schema import JudgeInput, judge_output_json_schema, validate_judge_output


MAX_API_RETRIES = 1
RAW_RESPONSE_SNIPPET_CHARS = 500


class LLMJudgeAPIConfigurationError(RuntimeError):
    """API mode 실행에 필요한 설정이 부족할 때 발생하는 오류."""


class LLMJudgeAPIError(RuntimeError):
    """API 호출 또는 응답 처리 중 발생한 표준 오류."""


def _safe_error_message(error: BaseException) -> str:
    """secret 값 노출 가능성을 줄인 짧은 오류 메시지를 만든다."""

    return f"{type(error).__name__}: {str(error)[:300]}"


def _is_timeout_error(error: BaseException) -> bool:
    """timeout 계열 오류인지 보수적으로 판정한다."""

    name = type(error).__name__.lower()
    return isinstance(error, TimeoutError) or "timeout" in name or "timedout" in name


def _is_transient_api_error(error: BaseException) -> bool:
    """재시도 가능한 일시적 API 오류인지 판정한다."""

    if _is_timeout_error(error):
        return True
    name = type(error).__name__.lower()
    text = str(error).lower()
    transient_names = ("ratelimit", "connection", "internalserver", "serviceunavailable", "apierror")
    transient_text = ("rate limit", "temporarily", "connection", "server error", "503", "502", "500")
    return any(token in name for token in transient_names) or any(token in text for token in transient_text)


def _empty_failure_result(judge_input: JudgeInput) -> dict[str, Any]:
    """실패 row에 공통으로 넣을 기본 필드를 만든다."""

    return {
        "id": judge_input.id,
        "question": judge_input.question,
        "judge_overall_score": "",
        "subscores": {},
        "risk_level": "",
        "hallucination_risk": "",
        "main_strengths": [],
        "main_weaknesses": [],
        "unsupported_or_risky_claims": [],
        "needs_human_review": True,
        "judge_comment": "",
        "calculated_overall_score": "",
        "overall_label": "",
        "score_cap_applied": False,
        "score_cap_reason": "",
        "score_disagreement_warning": False,
        "parse_error": False,
        "validation_error": False,
        "timeout_error": False,
        "structured_output_used": True,
        "fallback_json_mode_used": False,
        "retry_count": 0,
        "error": "",
    }


def _failure_result(
    judge_input: JudgeInput,
    error: str,
    *,
    parse_error: bool = False,
    validation_error: bool = False,
    timeout_error: bool = False,
    retry_count: int = 0,
    structured_output_used: bool = True,
    fallback_json_mode_used: bool = False,
) -> dict[str, Any]:
    """API 실패를 report에 저장 가능한 row로 변환한다."""

    result = _empty_failure_result(judge_input)
    result.update(
        {
            "parse_error": parse_error,
            "validation_error": validation_error,
            "timeout_error": timeout_error,
            "retry_count": retry_count,
            "structured_output_used": structured_output_used,
            "fallback_json_mode_used": fallback_json_mode_used,
            "error": error,
        }
    )
    return result


class OpenAIJudgeAdapter:
    """OpenAI Responses API를 사용해 Phase 4 Judge output을 생성한다."""

    def __init__(
        self,
        settings: LLMJudgeSettings,
        client: Any | None = None,
        max_retries: int = MAX_API_RETRIES,
    ) -> None:
        self.settings = settings
        self.client = client
        self.max_retries = max_retries

    def _ensure_ready(self) -> None:
        """API key와 model 설정을 확인한다."""

        if not self.settings.api_key_present:
            raise LLMJudgeAPIConfigurationError("LLM Judge API key is not configured. Set OPENAI_API_KEY in local .env or OS environment.")
        if not self.settings.model:
            raise LLMJudgeAPIConfigurationError("LLM Judge model is not configured. Set --llm-judge-model or LLM_JUDGE_MODEL.")

    def _client(self) -> Any:
        """OpenAI client를 지연 생성한다."""

        if self.client is not None:
            return self.client
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - 설치 환경에 따라 달라지는 방어 코드
            raise LLMJudgeAPIConfigurationError("openai package is required for api mode. Install evaluation requirements.") from exc
        self.client = OpenAI(api_key=self.settings.api_key, timeout=self.settings.timeout_seconds)
        return self.client

    def _messages(self, judge_input: JudgeInput, reference_mode: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """system prompt와 user payload-only message를 만든다."""

        payload = build_judge_case_payload(judge_input, reference_mode=reference_mode)
        return (
            [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            payload,
        )

    def _structured_text_format(self) -> dict[str, Any]:
        """Responses API structured output 설정을 만든다."""

        return {
            "format": {
                "type": "json_schema",
                "name": "phase4_llm_judge_output",
                "schema": judge_output_json_schema(),
                "strict": True,
            }
        }

    def _fallback_text_format(self) -> dict[str, Any]:
        """Structured Outputs 미지원 SDK를 위한 JSON object fallback 설정."""

        return {"format": {"type": "json_object"}}

    def _create_response(self, messages: list[dict[str, str]], *, structured: bool) -> tuple[Any, bool]:
        """OpenAI API를 호출하고 fallback 사용 여부를 반환한다."""

        text_format = self._structured_text_format() if structured else self._fallback_text_format()
        client = self._client()
        try:
            return (
                client.responses.create(
                    model=self.settings.model,
                    input=messages,
                    text=text_format,
                    temperature=self.settings.temperature,
                ),
                not structured,
            )
        except TypeError:
            if not structured:
                raise
            return (
                client.responses.create(
                    model=self.settings.model,
                    input=messages,
                    text=self._fallback_text_format(),
                    temperature=self.settings.temperature,
                ),
                True,
            )

    def _extract_response_payload(self, response: Any) -> dict[str, Any]:
        """SDK 응답에서 JSON payload를 추출한다."""

        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, dict):
            return parsed
        text = getattr(response, "output_text", None)
        if text is None and isinstance(response, dict):
            parsed = response.get("output_parsed")
            if isinstance(parsed, dict):
                return parsed
            text = response.get("output_text")
        if text is None:
            text = self._extract_nested_text(response)
        if not isinstance(text, str):
            raise ValueError("OpenAI response did not contain JSON text")
        return json.loads(text)

    def _extract_nested_text(self, response: Any) -> str | None:
        """Responses API의 nested output content에서 text를 추출한다."""

        output = getattr(response, "output", None)
        if output is None and isinstance(response, dict):
            output = response.get("output")
        for item in output or []:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            for part in content or []:
                text = getattr(part, "text", None)
                if text is None and isinstance(part, dict):
                    text = part.get("text")
                if isinstance(text, str):
                    return text
        return None

    def evaluate(self, judge_input: JudgeInput, reference_mode: str = "evidence_only") -> dict[str, Any]:
        """단일 JudgeInput을 API로 평가하고 local schema validation을 수행한다."""

        self._ensure_ready()
        messages, payload = self._messages(judge_input, reference_mode)
        evidence_count = len(payload.get("retrieved_evidence_summaries", []))
        retry_count = 0
        fallback_used = False
        last_error: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                retry_count += 1
            try:
                response, used_fallback = self._create_response(messages, structured=True)
                fallback_used = fallback_used or used_fallback
                parsed = self._extract_response_payload(response)
                processed = validate_judge_output(parsed, evidence_count=evidence_count, question=judge_input.question)
                processed["structured_output_used"] = not fallback_used
                processed["fallback_json_mode_used"] = fallback_used
                processed["retry_count"] = retry_count
                processed["timeout_error"] = False
                return processed
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    continue
                return _failure_result(
                    judge_input,
                    f"parse_error: response was not valid JSON. snippet={str(exc)[:RAW_RESPONSE_SNIPPET_CHARS]}",
                    parse_error=True,
                    retry_count=retry_count,
                    structured_output_used=not fallback_used,
                    fallback_json_mode_used=fallback_used,
                )
            except ValueError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    continue
                return _failure_result(
                    judge_input,
                    _safe_error_message(exc),
                    validation_error=True,
                    retry_count=retry_count,
                    structured_output_used=not fallback_used,
                    fallback_json_mode_used=fallback_used,
                )
            except Exception as exc:
                last_error = exc
                if _is_transient_api_error(exc) and attempt < self.max_retries:
                    continue
                return _failure_result(
                    judge_input,
                    _safe_error_message(exc),
                    timeout_error=_is_timeout_error(exc),
                    retry_count=retry_count,
                    structured_output_used=not fallback_used,
                    fallback_json_mode_used=fallback_used,
                )

        raise LLMJudgeAPIError(_safe_error_message(last_error or RuntimeError("unknown API adapter error")))
