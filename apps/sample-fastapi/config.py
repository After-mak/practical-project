"""FastAPI API와 Queue Worker가 공유하는 환경변수 설정을 정의합니다.

로컬 실행에서는 localhost Redis를 기본값으로 사용하고, Docker와 Kubernetes에서는
환경변수로 Redis 주소, Queue Key, Worker 처리 속도와 메트릭 포트를 변경합니다.
"""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _env_bool(name: str, default: bool = False) -> bool:
    """환경변수의 일반적인 참·거짓 문자열을 bool 값으로 변환합니다."""

    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of true/false, 1/0, yes/no, on/off")


@dataclass(frozen=True)
class Settings:
    """실행 시점의 환경변수를 타입이 지정된 설정 객체로 변환합니다.

    ``default_factory``를 사용하므로 모듈을 import한 시점이 아니라 Settings 객체를
    생성하는 시점의 환경변수가 반영됩니다. frozen=True로 생성 후 변경도 방지합니다.
    """

    # REDIS_URL이 있으면 URL을 우선 사용합니다. 비어 있으면 Host/Port 설정을 조합합니다.
    redis_url: str | None = field(default_factory=lambda: os.getenv("REDIS_URL") or None)
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    redis_db: int = field(default_factory=lambda: int(os.getenv("REDIS_DB", "0")))
    redis_password: str | None = field(
        default_factory=lambda: os.getenv("REDIS_PASSWORD") or None
    )
    redis_queue_key: str = field(
        default_factory=lambda: os.getenv(
            "REDIS_QUEUE_KEY", os.getenv("QUEUE_KEY", "dev:sample:queue")
        )
    )
    redis_ssl: bool = field(default_factory=lambda: _env_bool("REDIS_SSL", False))
    redis_ssl_cert_reqs: str = field(
        default_factory=lambda: os.getenv("REDIS_SSL_CERT_REQS", "required").lower()
    )
    redis_connect_timeout: float = field(
        default_factory=lambda: float(os.getenv("REDIS_CONNECT_TIMEOUT", "5"))
    )
    redis_socket_timeout: float = field(
        default_factory=lambda: float(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
    )
    redis_health_check_interval: int = field(
        default_factory=lambda: int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
    )
    redis_retry_attempts: int = field(
        default_factory=lambda: int(os.getenv("REDIS_RETRY_ATTEMPTS", "2"))
    )
    queue_max_retries: int = field(
        default_factory=lambda: int(os.getenv("QUEUE_MAX_RETRIES", "3"))
    )
    queue_visibility_timeout_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("QUEUE_VISIBILITY_TIMEOUT_SECONDS", "60")
        )
    )
    queue_recovery_interval_seconds: float = field(
        default_factory=lambda: float(os.getenv("QUEUE_RECOVERY_INTERVAL_SECONDS", "10"))
    )
    queue_completed_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("QUEUE_COMPLETED_TTL_SECONDS", "86400"))
    )

    # Worker 기본 작업 처리 시간과 prometheus_client HTTP 서버 포트입니다.
    worker_processing_seconds: float = field(
        default_factory=lambda: float(os.getenv("WORKER_PROCESSING_SECONDS", "0.25"))
    )
    worker_metrics_port: int = field(
        default_factory=lambda: int(os.getenv("WORKER_METRICS_PORT", "9100"))
    )
    worker_job_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("WORKER_JOB_TIMEOUT_SECONDS", "30"))
    )

    # 부하·오류·Queue 변경 API는 이 Secret과 X-Test-Token 헤더가 일치할 때만 허용합니다.
    load_test_token: str | None = field(
        default_factory=lambda: os.getenv("LOAD_TEST_TOKEN") or None
    )

    def __post_init__(self):
        """잘못된 TLS·Timeout 설정을 Redis 연결 전에 빠르게 차단합니다."""

        if self.redis_url:
            scheme = urlsplit(self.redis_url).scheme.lower()
            if scheme not in {"redis", "rediss"}:
                raise ValueError("REDIS_URL scheme must be redis or rediss")
        if self.redis_ssl_cert_reqs not in {"required", "optional", "none"}:
            raise ValueError("REDIS_SSL_CERT_REQS must be required, optional, or none")
        if self.redis_port <= 0 or self.redis_port > 65535:
            raise ValueError("REDIS_PORT must be between 1 and 65535")
        if self.redis_connect_timeout <= 0 or self.redis_socket_timeout <= 0:
            raise ValueError("Redis timeouts must be greater than zero")
        if self.redis_health_check_interval < 0 or self.redis_retry_attempts < 0:
            raise ValueError("Redis health check and retry values cannot be negative")
        if self.queue_max_retries < 0:
            raise ValueError("QUEUE_MAX_RETRIES cannot be negative")
        if (
            self.queue_visibility_timeout_seconds <= 0
            or self.queue_recovery_interval_seconds <= 0
            or self.queue_completed_ttl_seconds <= 0
            or self.worker_job_timeout_seconds <= 0
        ):
            raise ValueError("Queue and worker timeout values must be greater than zero")

    @property
    def redis_tls_enabled(self) -> bool:
        """URL 사용 시 scheme을, Host 방식에서는 REDIS_SSL 값을 TLS 기준으로 사용합니다."""

        if self.redis_url:
            return urlsplit(self.redis_url).scheme.lower() == "rediss"
        return self.redis_ssl
