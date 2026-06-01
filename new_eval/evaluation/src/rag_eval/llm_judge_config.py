"""Phase 4 LLM Judge 환경 설정 로더."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .llm_judge_prompt import PROMPT_VERSION, SCHEMA_VERSION


@dataclass
class LLMJudgeSettings:
    """LLM Judge 설정값 컨테이너.

    API key 값 자체는 repr에 포함하지 않고, 로그와 리포트에는 존재 여부만 기록한다.
    """

    provider: str = "openai"
    model: str = ""
    temperature: float = 0.0
    max_input_chars: int = 6000
    timeout_seconds: int = 60
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    api_key_present: bool = False
    api_key: str = field(default="", repr=False)


def _load_dotenv_if_available(env_path: Path) -> None:
    """python-dotenv가 설치되어 있으면 .env를 로드한다."""

    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(env_path, override=False)


def _read_float(name: str, default: float) -> float:
    """환경변수 float 값을 안전하게 읽는다."""

    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _read_int(name: str, default: int) -> int:
    """환경변수 int 값을 안전하게 읽는다."""

    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def load_llm_judge_settings(evaluation_root: Path | None = None, model_override: str = "") -> LLMJudgeSettings:
    """`.env`와 OS 환경변수에서 LLM Judge 설정을 읽는다."""

    if evaluation_root is None:
        evaluation_root = Path(__file__).resolve().parents[2]
    if evaluation_root is not None:
        _load_dotenv_if_available(evaluation_root / ".env")

    api_key = os.getenv("OPENAI_API_KEY", "")
    model = model_override or os.getenv("LLM_JUDGE_MODEL", "")
    return LLMJudgeSettings(
        provider=os.getenv("LLM_JUDGE_PROVIDER", "openai"),
        model=model,
        temperature=_read_float("LLM_JUDGE_TEMPERATURE", 0.0),
        max_input_chars=_read_int("LLM_JUDGE_MAX_INPUT_CHARS", 6000),
        timeout_seconds=_read_int("LLM_JUDGE_TIMEOUT_SECONDS", 60),
        prompt_version=os.getenv("LLM_JUDGE_PROMPT_VERSION", PROMPT_VERSION),
        schema_version=os.getenv("LLM_JUDGE_SCHEMA_VERSION", SCHEMA_VERSION),
        api_key_present=bool(api_key),
        api_key=api_key,
    )
