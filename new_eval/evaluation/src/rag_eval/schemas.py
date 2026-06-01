"""평가 데이터 구조를 설명하는 dataclass 모음."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedContext:
    """검색 결과 context 한 개의 표준 구조."""

    rank: int | float | None = None
    filename: str | None = None
    doc_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentMeta:
    """실험 로그에 공통으로 들어가는 식별 정보."""

    experiment_id: str
    experiment_name: str
    run_datetime: str
    notes: str = ""

