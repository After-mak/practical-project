"""FastAPI 엔드포인트, Redis 장애 응답과 Prometheus 노출 동작을 검증합니다."""

import fakeredis
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from main import app, get_queue_service
from queue_service import QueueService


def make_client():
    """실제 Redis 없이 독립 실행할 수 있는 FakeRedis 기반 TestClient를 만듭니다."""

    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    app.dependency_overrides[get_queue_service] = lambda: service
    return TestClient(app), service


def test_health_readiness_and_shared_queue_api():
    client, service = make_client()
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"status": "ready", "redis": "ok"}

        joined = client.post(
            "/api/queue/join",
            json={"job_type": "load", "payload": {"processing_seconds": 0}},
        )
        assert joined.status_code == 200
        assert joined.json()["queue_length"] == 1
        assert service.length() == 1
        assert client.get("/api/queue/status").json()["queue_length"] == 1

        processed = client.post("/api/queue/process")
        assert processed.json()["queue_length"] == 0
        assert processed.json()["job"]["type"] == "load"
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_reset_and_prometheus_metrics():
    client, _service = make_client()
    try:
        client.post("/api/queue/join")
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "sample_queue_length 1.0" in metrics.text
        assert "sample_queue_enter_total" in metrics.text
        assert "sample_http_requests_total" in metrics.text

        reset = client.delete("/api/queue/reset")
        assert reset.json()["deleted_items"] == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_redis_failure_returns_service_unavailable():
    class UnavailableQueue:
        def ping(self):
            raise ConnectionError("redis is down")

        def enqueue(self, *_args, **_kwargs):
            raise ConnectionError("redis is down")

    app.dependency_overrides[get_queue_service] = lambda: UnavailableQueue()
    client = TestClient(app)
    try:
        ready = client.get("/ready")
        joined = client.post("/api/queue/join")
        assert ready.status_code == 503
        assert joined.status_code == 503
        assert "Redis unavailable" in ready.json()["detail"]
    finally:
        client.close()
        app.dependency_overrides.clear()
