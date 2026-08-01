"""Worker가 각 Queue 작업을 한 번씩 처리하고 빈 Queue에서 대기하는지 검증합니다."""

import fakeredis
from redis.exceptions import ConnectionError

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


def test_worker_retries_failure_and_succeeds_without_losing_job():
    class FailOnceWorker(QueueWorker):
        calls = 0

        def process_job(self, job):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")

    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True), "test:queue", max_retries=2
    )
    worker = FailOnceWorker(service, processing_seconds=0)
    job = service.enqueue("retry")

    assert worker.run_once(timeout=0) is True
    assert service.length() == 1
    assert service.processing_length() == 0
    assert worker.run_once(timeout=0) is True
    assert service.length() == 0
    assert service.processing_length() == 0
    assert service.dead_letter_length() == 0
    assert service.is_completed(job["id"])


def test_worker_timeout_retries_then_dead_letters_job():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        max_retries=0,
    )
    worker = QueueWorker(
        service, processing_seconds=0, job_timeout_seconds=0.01
    )
    service.enqueue("timeout", {"processing_seconds": 1})

    assert worker.run_once(timeout=0) is True
    assert service.length() == 0
    assert service.processing_length() == 0
    assert service.dead_letter_length() == 1


def test_restarted_worker_processes_job_recovered_from_crashed_worker():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    crashed_service = QueueService(
        redis_client,
        "test:queue",
        visibility_timeout_seconds=1,
    )
    job = crashed_service.enqueue("recover", {"processing_seconds": 0})
    reservation = crashed_service.reserve(timeout=0)
    assert reservation is not None

    restarted_service = QueueService(
        redis_client,
        "test:queue",
        visibility_timeout_seconds=1,
    )
    assert restarted_service.recover_stale(now_timestamp=10**12)["retried"] == 1
    restarted_worker = QueueWorker(restarted_service, processing_seconds=0)

    assert restarted_worker.run_once(timeout=0) is True
    assert restarted_service.length() == 0
    assert restarted_service.processing_length() == 0
    assert restarted_service.dead_letter_length() == 0
    assert restarted_service.is_completed(job["id"]) is True


def test_worker_loop_continues_after_temporary_redis_failure(monkeypatch):
    class TemporarilyUnavailableService:
        calls = 0

        def recover_stale(self):
            return {"retried": 0, "dead_lettered": 0, "already_completed": 0}

        def reserve(self, timeout=1):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary outage")
            worker.stop_event.set()
            return None

        def length(self):
            return 0

    service = TemporarilyUnavailableService()
    worker = QueueWorker(service, processing_seconds=0)
    monkeypatch.setattr(worker.stop_event, "wait", lambda _seconds: False)

    worker.run()

    assert service.calls == 2
