"""저장소 어느 경로에서 실행해도 애플리케이션 모듈을 찾도록 pytest를 설정합니다."""

import sys
from pathlib import Path


# 저장소 루트 또는 애플리케이션 디렉터리 어디에서 pytest를 실행해도
# main.py와 Queue/Worker 모듈을 동일하게 import할 수 있도록 경로를 등록합니다.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
