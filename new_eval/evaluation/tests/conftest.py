"""테스트에서 evaluation/src 아래 rag_eval 패키지를 import하기 위한 설정."""

from __future__ import annotations

import sys
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = EVALUATION_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
