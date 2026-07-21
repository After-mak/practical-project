"""ElastiCache와 로컬 Redis가 공통으로 사용하는 동기 Client를 생성합니다."""

from redis import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError
from redis.retry import Retry

from config import Settings


def create_redis_client(settings: Settings | None = None) -> Redis:
    """API와 Worker가 공통으로 사용할 Redis 연결 객체를 생성합니다.

    응답을 문자열로 바로 사용할 수 있도록 ``decode_responses``를 활성화하고,
    Redis 장애 시 요청이 무기한 대기하지 않도록 연결·소켓 제한 시간을 적용합니다.
    실제 네트워크 연결은 명령을 처음 실행할 때 Redis-py가 지연 생성합니다.
    """

    settings = settings or Settings()
    common_options = {
        "socket_timeout": settings.redis_socket_timeout,
        "socket_connect_timeout": settings.redis_connect_timeout,
        "decode_responses": True,
        "health_check_interval": settings.redis_health_check_interval,
        "retry": Retry(
            ExponentialBackoff(cap=1.0, base=0.1),
            retries=settings.redis_retry_attempts,
        ),
        "retry_on_error": [ConnectionError, TimeoutError],
    }

    # URL은 redis:// 또는 rediss:// scheme으로 TLS 사용 여부를 명시합니다. Password를
    # 별도 환경변수로 제공하면 URL에 Secret을 넣지 않고도 인증할 수 있습니다.
    if settings.redis_url:
        url_options = dict(common_options)
        if settings.redis_password is not None:
            url_options["password"] = settings.redis_password
        if settings.redis_tls_enabled:
            url_options["ssl_cert_reqs"] = settings.redis_ssl_cert_reqs
        return Redis.from_url(settings.redis_url, **url_options)

    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password,
        ssl=settings.redis_tls_enabled,
        ssl_cert_reqs=settings.redis_ssl_cert_reqs,
        **common_options,
    )
