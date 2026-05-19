"""Convenience entrypoint for the nested evaluation module."""

from __future__ import annotations

import sys
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
SRC_DIR = EVALUATION_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rag_eval.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
