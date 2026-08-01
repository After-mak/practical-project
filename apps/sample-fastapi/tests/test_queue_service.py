"""Redis Queue의 reserve·ACK·retry·DLQ·장애 복구 동작을 검증합니다."""

from datetime import datetime, timezone

import fakeredis

from queue_service import QueueService


def test_services_share_queue_and_queue_survives_service_restart():
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    first = QueueService(redis_client, "test:queue")
    second = QueueService(redis_client, "test:queue")

    job = first.enqueue("sample", {"value": 1})

    assert second.length() == 1
    assert second.dequeue(timeout=0) == job
    assert first.length() == 0


def test_bulk_enqueue_uses_unique_ids_and_preserves_fifo_order():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")

    jobs = service.enqueue_many(3, "bulk", {"value": 1})

    assert service.length() == 3
    assert len({job["id"] for job in jobs}) == 3
    assert [service.dequeue(timeout=0) for _ in jobs] == jobs


def test_clear_returns_deleted_item_count():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    service.enqueue("one")
    service.enqueue("two")

    assert service.clear() == 2
    assert service.length() == 0


def test_clear_removes_processing_dead_letter_leases_and_completed_markers():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        max_retries=0,
    )
    completed = service.enqueue("completed")
    completed_reservation = service.reserve(timeout=0)
    assert completed_reservation is not None
    service.acknowledge(completed_reservation)

    service.enqueue("processing")
    assert service.reserve(timeout=0) is not None
    service.enqueue("dead-letter")
    failed = service.reserve(timeout=0)
    assert failed is not None
    service.retry_or_dead_letter(failed, "failure")

    assert service.clear() == 2
    assert service.processing_length() == 0
    assert service.dead_letter_length() == 0
    assert service.redis.zcard(service.leases_key) == 0
    assert service.is_completed(completed["id"]) is False


def test_reserve_moves_job_to_processing_and_ack_removes_it():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    job = service.enqueue("sample")

    reservation = service.reserve(timeout=0)

    assert reservation is not None
    assert reservation.job == job
    assert service.length() == 0
    assert service.processing_length() == 1
    assert service.acknowledge(reservation) is True
    assert service.processing_length() == 0
    assert service.is_completed(job["id"]) is True


def test_failed_job_retries_then_moves_to_dead_letter_queue():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        max_retries=1,
    )
    service.enqueue("always-fails")

    first = service.reserve(timeout=0)
    assert first is not None
    assert service.retry_or_dead_letter(first, "first failure") == "retry"
    assert service.length() == 1

    second = service.reserve(timeout=0)
    assert second is not None
    assert second.job["attempts"] == 1
    assert service.retry_or_dead_letter(second, "second failure") == "dead-letter"
    assert service.length() == 0
    assert service.processing_length() == 0
    assert service.dead_letter_length() == 1


def test_stale_processing_job_is_recovered_after_worker_crash():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        max_retries=2,
        visibility_timeout_seconds=10,
    )
    job = service.enqueue("crash-test")
    reservation = service.reserve(timeout=0)
    assert reservation is not None

    future = datetime.now(timezone.utc).timestamp() + 11
    recovered = service.recover_stale(now_timestamp=future)

    assert recovered == {
        "retried": 1,
        "dead_lettered": 0,
        "already_completed": 0,
    }
    assert service.processing_length() == 0
    assert service.length() == 1
    retried = service.reserve(timeout=0)
    assert retried is not None
    assert retried.job["id"] == job["id"]
    assert retried.job["attempts"] == 1


def test_completed_job_is_not_requeued_by_stale_recovery():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        visibility_timeout_seconds=1,
    )
    service.enqueue("complete")
    reservation = service.reserve(timeout=0)
    assert reservation is not None
    assert service.acknowledge(reservation)

    recovered = service.recover_stale(
        now_timestamp=datetime.now(timezone.utc).timestamp() + 2
    )

    assert recovered == {
        "retried": 0,
        "dead_lettered": 0,
        "already_completed": 0,
    }
    assert service.length() == 0
    assert service.processing_length() == 0


def test_processing_job_without_lease_is_eventually_recoverable():
    service = QueueService(
        fakeredis.FakeRedis(decode_responses=True),
        "test:queue",
        visibility_timeout_seconds=10,
    )
    service.enqueue("orphan")
    reservation = service.reserve(timeout=0)
    assert reservation is not None
    service.redis.zrem(service.leases_key, reservation.raw)

    first_scan = service.recover_stale(now_timestamp=100)
    second_scan = service.recover_stale(now_timestamp=111)

    assert first_scan == {
        "retried": 0,
        "dead_lettered": 0,
        "already_completed": 0,
    }
    assert second_scan["retried"] == 1
    assert service.processing_length() == 0
    assert service.length() == 1
