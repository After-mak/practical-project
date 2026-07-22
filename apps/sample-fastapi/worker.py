"""Redis Queue 작업을 소비하는 독립 Worker 프로세스입니다.

Docker에서는 ``python worker.py``로 실행하고 Kubernetes에서는 queue-worker
Deployment의 컨테이너 Command로 실행합니다. BLPOP으로 작업을 기다리며 9100 포트에
Worker 전용 Prometheus 메트릭을 노출합니다.
"""

import logging
import signal
import threading
import time
from typing import Any

from prometheus_client import start_http_server
from redis.exceptions import RedisError

from config import Settings
from metrics import (
    QUEUE_FAILED_TOTAL,
    QUEUE_LENGTH,
    QUEUE_PROCESSED_TOTAL,
    WORKER_ACTIVE_JOBS,
    WORKER_PROCESSED_TOTAL,
    WORKER_PROCESSING_DURATION_SECONDS,
)
from queue_service import QueueService, create_queue_service


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("queue-worker")


class QueueWorker:
    """Queue 소비, 작업 처리, 메트릭 기록과 정상 종료를 담당합니다."""

    def __init__(self, service: QueueService, processing_seconds: float = 0.25):
        """QueueService와 작업당 기본 처리 시간을 주입받습니다."""

        self.service = service
        self.processing_seconds = max(0.0, processing_seconds)
        self.stop_event = threading.Event()

    def stop(self, *_args):
        """SIGTERM 또는 SIGINT 수신 시 반복 루프가 종료되도록 알립니다.

        현재 처리 중인 작업은 중단하지 않고 완료한 뒤 다음 루프에서 종료합니다.
        """

        logger.info("Shutdown requested; waiting for the active job to finish")
        self.stop_event.set()

    def process_job(self, job: dict[str, Any]):
        """샘플 작업의 처리 시간을 재현합니다.

        payload의 processing_seconds를 사용할 수 있으며, 실수로 지나치게 긴 값을
        전달해 Worker가 멈추지 않도록 0~30초 범위로 제한합니다.
        """

        requested_seconds = job.get("payload", {}).get(
            "processing_seconds", self.processing_seconds
        )
        processing_seconds = min(max(float(requested_seconds), 0.0), 30.0)
        time.sleep(processing_seconds)

    def run_once(self, timeout: int = 1) -> bool:
        """작업을 최대 하나 처리하고 처리 여부를 반환합니다.

        작업 처리 중에는 Active Gauge를 증가시키고, 성공·실패 Counter와 처리 시간
        Histogram 및 최신 Redis Queue Length를 반드시 갱신합니다.
        """

        job = self.service.dequeue(timeout=timeout)
        if job is None:
            QUEUE_LENGTH.set(self.service.length())
            return False

        WORKER_ACTIVE_JOBS.inc()
        started_at = time.perf_counter()
        try:
            self.process_job(job)
            QUEUE_PROCESSED_TOTAL.inc()
            WORKER_PROCESSED_TOTAL.inc()
            logger.info("Processed job id=%s type=%s", job["id"], job["type"])
        except Exception:
            QUEUE_FAILED_TOTAL.inc()
            logger.exception("Failed to process job id=%s", job.get("id"))
        finally:
            WORKER_PROCESSING_DURATION_SECONDS.observe(time.perf_counter() - started_at)
            WORKER_ACTIVE_JOBS.dec()
            QUEUE_LENGTH.set(self.service.length())
        return True

    def run(self):
        """종료 신호를 받을 때까지 Queue를 소비하며 Redis 장애 시 재시도합니다."""

        logger.info("Queue worker started")
        while not self.stop_event.is_set():
            try:
                self.run_once(timeout=1)
            except RedisError:
                QUEUE_FAILED_TOTAL.inc()
                logger.exception("Redis operation failed; retrying")
                self.stop_event.wait(2)
        logger.info("Queue worker stopped")


def main():
    """환경 설정, 종료 Signal, 메트릭 서버와 Worker 루프를 초기화합니다."""

    settings = Settings()
    worker = QueueWorker(create_queue_service(settings), settings.worker_processing_seconds)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    start_http_server(settings.worker_metrics_port)
    logger.info("Worker metrics listening on port %s", settings.worker_metrics_port)
    worker.run()


if __name__ == "__main__":
    main()
