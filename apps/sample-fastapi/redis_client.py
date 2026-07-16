"""설정값을 사용해 Redis 동기 클라이언트를 생성하는 모듈입니다."""

from redis import Redis

from config import Settings


def create_redis_client(settings: Settings | None = None) -> Redis:
    """API와 Worker가 공통으로 사용할 Redis 연결 객체를 생성합니다.

    응답을 문자열로 바로 사용할 수 있도록 ``decode_responses``를 활성화하고,
    Redis 장애 시 요청이 무기한 대기하지 않도록 연결·소켓 제한 시간을 적용합니다.
    실제 네트워크 연결은 명령을 처음 실행할 때 Redis-py가 지연 생성합니다.
    """

    settings = settings or Settings()
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_timeout,
        decode_responses=True,
        health_check_interval=30,
    )
