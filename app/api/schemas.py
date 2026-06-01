from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    issuers: list[str] = Field(default_factory=list)
    max_contexts: int = 5
    debug: bool = True


class AskResponse(BaseModel):
    answer: str
    issuers: list[str]
    question_type: str
    route: list[str]
    retrieved_contexts: list[dict[str, Any]]
    manual_lookup_contexts: list[dict[str, Any]] = Field(default_factory=list)
    latency_sec: float
    debug: dict[str, Any] = Field(default_factory=dict)


class IssuersResponse(BaseModel):
    issuers: list[str]
