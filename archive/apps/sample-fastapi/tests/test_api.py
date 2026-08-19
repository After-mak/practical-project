"""FastAPI 엔드포인트, Redis 장애 응답과 Prometheus 노출 동작을 검증합니다."""

import fakeredis
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from config import Settings
from main import app, get_queue_service, get_settings
from queue_service import QueueService


TEST_TOKEN = "unit-test-load-token"
TEST_HEADERS = {"X-Test-Token": TEST_TOKEN}


def make_client():
    """실제 Redis 없이 독립 실행할 수 있는 FakeRedis 기반 TestClient를 만듭니다."""

    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    app.dependency_overrides[get_queue_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: Settings(load_test_token=TEST_TOKEN)
    return TestClient(app), service


def test_health_readiness_and_shared_queue_api():
    client, service = make_client()
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"status": "ready", "redis": "ok"}

        joined = client.post(
            "/api/queue/join",
            json={"job_type": "load", "payload": {"processing_seconds": 0}},
            headers=TEST_HEADERS,
        )
        assert joined.status_code == 200
        assert joined.json()["queue_length"] == 1
        assert service.length() == 1
        assert client.get("/api/queue/status").json()["queue_length"] == 1

        processed = client.post("/api/queue/process", headers=TEST_HEADERS)
        assert processed.json()["queue_length"] == 0
        assert processed.json()["job"]["type"] == "load"
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_reset_and_prometheus_metrics():
    client, _service = make_client()
    try:
        client.post("/api/queue/join", headers=TEST_HEADERS)
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "sample_queue_length 1.0" in metrics.text
        assert "sample_queue_enter_total" in metrics.text
        assert "sample_http_requests_total" in metrics.text

        reset = client.delete("/api/queue/reset", headers=TEST_HEADERS)
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
    app.dependency_overrides[get_settings] = lambda: Settings(load_test_token=TEST_TOKEN)
    client = TestClient(app)
    try:
        ready = client.get("/ready")
        joined = client.post("/api/queue/join", headers=TEST_HEADERS)
        assert ready.status_code == 503
        assert joined.status_code == 503
        assert "Redis unavailable" in ready.json()["detail"]
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_load_endpoints_require_valid_token():
    client, service = make_client()
    try:
        protected_requests = (
            ("get", "/api/cpu"),
            ("get", "/api/memory"),
            ("get", "/api/slow"),
            ("get", "/api/error"),
            ("post", "/api/queue/join"),
            ("post", "/api/queue/process"),
            ("delete", "/api/queue/reset"),
        )
        for method, path in protected_requests:
            assert getattr(client, method)(path).status_code == 403
            assert (
                getattr(client, method)(
                    path, headers={"X-Test-Token": "wrong-token"}
                ).status_code
                == 403
            )

        assert client.post(
            "/api/queue/join", headers=TEST_HEADERS
        ).status_code == 200
        assert service.length() == 1
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_bulk_queue_join_is_authenticated_and_bounded():
    client, service = make_client()
    try:
        denied = client.post("/api/queue/bulk", json={"count": 3})
        assert denied.status_code == 403

        accepted = client.post(
            "/api/queue/bulk",
            json={"count": 3, "job_type": "bulk", "payload": {"value": 1}},
            headers=TEST_HEADERS,
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] == 3
        assert len(accepted.json()["job_ids"]) == 3
        assert service.length() == 3

        too_many = client.post(
            "/api/queue/bulk", json={"count": 1001}, headers=TEST_HEADERS
        )
        assert too_many.status_code == 422
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_health_ready_status_and_metrics_remain_unprotected():
    client, _service = make_client()
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert client.get("/api/queue/status").status_code == 200
        assert client.get("/metrics").status_code == 200
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_protected_api_fails_closed_when_token_is_not_configured():
    service = QueueService(fakeredis.FakeRedis(decode_responses=True), "test:queue")
    app.dependency_overrides[get_queue_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: Settings(load_test_token=None)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/queue/join", headers={"X-Test-Token": "untrusted-value"}
        )
        assert response.status_code == 503
        assert service.length() == 0
    finally:
        client.close()
        app.dependency_overrides.clear()
