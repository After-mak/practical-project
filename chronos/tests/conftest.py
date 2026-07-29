"""Chronos 소스 디렉터리를 테스트 import 경로에 추가합니다."""

import sys
from pathlib import Path


CHRONOS_DIR = Path(__file__).resolve().parents[1]
if str(CHRONOS_DIR) not in sys.path:
    sys.path.insert(0, str(CHRONOS_DIR))
