"""FastAPI API와 Queue Worker가 공유하는 환경변수 설정을 정의합니다.

로컬 실행에서는 localhost Redis를 기본값으로 사용하고, Docker와 Kubernetes에서는
환경변수로 Redis 주소, Queue Key, Worker 처리 속도와 메트릭 포트를 변경합니다.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """실행 시점의 환경변수를 타입이 지정된 설정 객체로 변환합니다.

    ``default_factory``를 사용하므로 모듈을 import한 시점이 아니라 Settings 객체를
    생성하는 시점의 환경변수가 반영됩니다. frozen=True로 생성 후 변경도 방지합니다.
    """

    # Redis 연결 정보입니다. PASSWORD가 빈 문자열이면 인증 없이 연결합니다.
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    redis_db: int = field(default_factory=lambda: int(os.getenv("REDIS_DB", "0")))
    redis_password: str | None = field(
        default_factory=lambda: os.getenv("REDIS_PASSWORD") or None
    )
    redis_queue_key: str = field(
        default_factory=lambda: os.getenv("REDIS_QUEUE_KEY", "dev:sample:queue")
    )
    redis_socket_timeout: float = field(
        default_factory=lambda: float(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
    )

    # Worker 기본 작업 처리 시간과 prometheus_client HTTP 서버 포트입니다.
    worker_processing_seconds: float = field(
        default_factory=lambda: float(os.getenv("WORKER_PROCESSING_SECONDS", "0.25"))
    )
    worker_metrics_port: int = field(
        default_factory=lambda: int(os.getenv("WORKER_METRICS_PORT", "9100"))
    )
