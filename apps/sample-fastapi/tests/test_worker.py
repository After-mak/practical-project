"""Worker가 각 Queue 작업을 한 번씩 처리하고 빈 Queue에서 대기하는지 검증합니다."""

import fakeredis

from queue_service import QueueService
from metrics import WORKER_PROCESSED_TOTAL
from worker import QueueWorker


def test_worker_processes_each_queued_job_once():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    worker = QueueWorker(service, processing_seconds=0)
    processed_before = WORKER_PROCESSED_TOTAL._value.get()
    first = service.enqueue("first")
    second = service.enqueue("second")

    assert worker.run_once(timeout=0) is True
    assert worker.run_once(timeout=0) is True
    assert worker.run_once(timeout=0) is False
    assert service.length() == 0
    assert first["id"] != second["id"]
    assert WORKER_PROCESSED_TOTAL._value.get() == processed_before + 2
