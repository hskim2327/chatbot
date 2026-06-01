"""Windows 한글 경로와 OneDrive 경로를 안전하게 다루기 위한 유틸리티."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """프로젝트 루트 경로를 반환한다."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "data" / "eval").exists() and (parent / "new_data").exists() and (parent / "AGENTS.md").exists():
            return parent
    return current.parents[3]


def resolve_path(path_value: str | Path, base_dir: Path | None = None) -> Path:
    """상대경로는 프로젝트 루트 기준으로 해석하고 절대경로는 그대로 사용한다."""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return ((base_dir or project_root()) / path).resolve()


def ensure_parent(path: Path) -> None:
    """파일을 쓰기 전에 부모 폴더를 생성한다."""

    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> None:
    """폴더가 없으면 생성한다."""

    path.mkdir(parents=True, exist_ok=True)


def safe_json_value(value: Any) -> Any:
    """JSON으로 저장할 수 있도록 NaN 값을 None으로 바꾼다."""

    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: safe_json_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [safe_json_value(inner) for inner in value]
    return value
