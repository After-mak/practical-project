"""로컬 Redis와 ElastiCache TLS 환경의 공통 설정 및 Client 구성을 검증합니다."""

import pytest
from redis.connection import SSLConnection

from config import Settings
from redis_client import create_redis_client


REDIS_ENV_NAMES = (
    "REDIS_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
    "REDIS_SSL",
    "REDIS_SSL_CERT_REQS",
    "REDIS_CONNECT_TIMEOUT",
    "REDIS_SOCKET_TIMEOUT",
    "REDIS_HEALTH_CHECK_INTERVAL",
    "REDIS_RETRY_ATTEMPTS",
    "REDIS_QUEUE_KEY",
    "QUEUE_KEY",
    "QUEUE_MAX_RETRIES",
    "QUEUE_VISIBILITY_TIMEOUT_SECONDS",
    "QUEUE_RECOVERY_INTERVAL_SECONDS",
    "QUEUE_COMPLETED_TTL_SECONDS",
    "WORKER_JOB_TIMEOUT_SECONDS",
    "LOAD_TEST_TOKEN",
)


def clear_redis_environment(monkeypatch):
    """개발자 PC 환경변수가 설정 테스트에 영향을 주지 않게 제거합니다."""

    for name in REDIS_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_local_redis_defaults_use_plain_connection(monkeypatch):
    clear_redis_environment(monkeypatch)

    settings = Settings()
    client = create_redis_client(settings)
    options = client.connection_pool.connection_kwargs

    assert settings.redis_tls_enabled is False
    assert options["host"] == "localhost"
    assert options["port"] == 6379
    assert options["socket_connect_timeout"] == 5
    assert options["health_check_interval"] == 30


def test_elasticache_host_settings_enable_tls_and_certificate_validation():
    settings = Settings(
        redis_host="cache.example.local",
        redis_ssl=True,
        redis_ssl_cert_reqs="required",
        redis_password="not-logged-secret",
    )
    client = create_redis_client(settings)
    options = client.connection_pool.connection_kwargs

    assert settings.redis_tls_enabled is True
    assert options["host"] == "cache.example.local"
    assert client.connection_pool.connection_class is SSLConnection
    assert options["ssl_cert_reqs"] == "required"
    assert options["password"] == "not-logged-secret"


def test_rediss_url_takes_precedence_over_redis_ssl_flag():
    settings = Settings(
        redis_url="rediss://cache.example.local:6379/0",
        redis_ssl=False,
        redis_password="separate-secret",
    )
    client = create_redis_client(settings)
    options = client.connection_pool.connection_kwargs

    assert settings.redis_tls_enabled is True
    assert options["host"] == "cache.example.local"
    assert client.connection_pool.connection_class is SSLConnection
    assert options["password"] == "separate-secret"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"redis_url": "http://cache.example.local"}, "scheme"),
        ({"redis_ssl_cert_reqs": "invalid"}, "REDIS_SSL_CERT_REQS"),
        ({"redis_connect_timeout": 0}, "timeouts"),
        ({"redis_retry_attempts": -1}, "retry"),
        ({"queue_max_retries": -1}, "QUEUE_MAX_RETRIES"),
        ({"queue_visibility_timeout_seconds": 0}, "timeout"),
        ({"worker_job_timeout_seconds": 0}, "timeout"),
    ],
)
def test_invalid_redis_settings_fail_fast(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Settings(**kwargs)


def test_queue_reliability_and_load_token_settings_are_read_from_environment(
    monkeypatch,
):
    clear_redis_environment(monkeypatch)
    monkeypatch.setenv("QUEUE_MAX_RETRIES", "5")
    monkeypatch.setenv("QUEUE_VISIBILITY_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("QUEUE_RECOVERY_INTERVAL_SECONDS", "7")
    monkeypatch.setenv("QUEUE_COMPLETED_TTL_SECONDS", "3600")
    monkeypatch.setenv("WORKER_JOB_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("LOAD_TEST_TOKEN", "secret-value")

    settings = Settings()

    assert settings.queue_max_retries == 5
    assert settings.queue_visibility_timeout_seconds == 45
    assert settings.queue_recovery_interval_seconds == 7
    assert settings.queue_completed_ttl_seconds == 3600
    assert settings.worker_job_timeout_seconds == 12
    assert settings.load_test_token == "secret-value"
