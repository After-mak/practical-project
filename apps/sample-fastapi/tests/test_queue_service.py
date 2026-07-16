"""Redis Queue의 공유 상태, FIFO 소비와 초기화 동작을 검증합니다."""

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


def test_clear_returns_deleted_item_count():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    service.enqueue("one")
    service.enqueue("two")

    assert service.clear() == 2
    assert service.length() == 0
