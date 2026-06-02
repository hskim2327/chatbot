"""Convenience wrapper for the evaluation CLI."""

from __future__ import annotations

import runpy
from pathlib import Path


TARGET = Path(__file__).resolve().parents[1] / "evaluation" / "scripts" / "run_evaluation.py"


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
