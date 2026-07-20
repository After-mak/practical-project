"""API와 Worker가 노출하는 Prometheus 메트릭을 한곳에서 정의합니다.

메트릭 객체를 모듈 전역에서 한 번만 생성해 중복 등록 오류를 방지하고,
API의 ``/metrics``와 Worker의 9100 포트에서 동일한 이름 체계를 사용합니다.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


# Redis에서 조회한 현재 대기 작업 수입니다. KEDA Prometheus Trigger가 사용합니다.
QUEUE_LENGTH = Gauge("sample_queue_length", "Current Redis queue length")

# Queue 등록, 처리 성공, 처리·연결 실패 누적 횟수입니다.
QUEUE_ENTER_TOTAL = Counter("sample_queue_enter_total", "Jobs added to the queue")
QUEUE_PROCESSED_TOTAL = Counter("sample_queue_processed_total", "Jobs processed successfully")
QUEUE_FAILED_TOTAL = Counter("sample_queue_failed_total", "Queue or worker operation failures")

# 각 Worker 프로세스가 현재 처리 중인 작업과 처리 시간 분포를 기록합니다.
WORKER_PROCESSED_TOTAL = Counter(
    "worker_processed_total", "Jobs processed successfully by this worker"
)
WORKER_ACTIVE_JOBS = Gauge("sample_worker_active_jobs", "Jobs currently processed by this worker")
WORKER_PROCESSING_DURATION_SECONDS = Histogram(
    "sample_worker_processing_duration_seconds",
    "Worker job processing duration",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

# API 요청 수, 오류 수, 응답 시간을 Method·Path·Status 기준으로 관측합니다.
HTTP_REQUESTS_TOTAL = Counter(
    "sample_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "path", "status"),
)
HTTP_ERRORS_TOTAL = Counter(
    "sample_http_errors_total",
    "HTTP error responses returned by the API",
    ("method", "path", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "sample_request_duration_seconds",
    "HTTP request duration",
    ("method", "path"),
)


def render_metrics() -> bytes:
    """현재 프로세스의 모든 메트릭을 Prometheus exposition 형식으로 반환합니다."""

    return generate_latest()


__all__ = ["CONTENT_TYPE_LATEST", "render_metrics"]
