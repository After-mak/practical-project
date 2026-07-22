"""Redis List를 사용하는 공유 Queue의 저장·조회·소비 동작을 제공합니다."""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis import Redis

from config import Settings
from redis_client import create_redis_client


class QueueService:
    """FastAPI와 여러 Worker가 동일한 Redis Queue를 사용하도록 캡슐화합니다.

    작업은 RPUSH로 오른쪽에 추가하고 LPOP/BLPOP으로 왼쪽에서 가져오므로
    먼저 등록한 작업부터 처리되는 FIFO 순서를 유지합니다.
    """

    def __init__(self, redis_client: Redis, queue_key: str):
        """사용할 Redis 클라이언트와 서비스별 Queue Key를 저장합니다."""

        self.redis = redis_client
        self.queue_key = queue_key

    def ping(self) -> bool:
        """Readiness Probe에서 사용할 Redis 연결 상태를 반환합니다."""

        return bool(self.redis.ping())

    def enqueue(self, job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """고유 ID와 등록 시각을 포함한 작업을 JSON으로 직렬화해 Queue에 추가합니다."""

        job = {
            "id": str(uuid4()),
            "type": job_type,
            "payload": payload or {},
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        self.redis.rpush(self.queue_key, json.dumps(job, separators=(",", ":")))
        return job

    def dequeue(self, timeout: int = 1) -> dict[str, Any] | None:
        """Queue의 가장 오래된 작업을 하나 가져옵니다.

        timeout이 0 이하이면 API의 수동 처리처럼 즉시 반환하는 LPOP을 사용하고,
        양수이면 Worker가 새 작업을 기다릴 수 있도록 BLPOP을 사용합니다.
        """

        if timeout <= 0:
            raw = self.redis.lpop(self.queue_key)
        else:
            result = self.redis.blpop(self.queue_key, timeout=timeout)
            raw = result[1] if result else None
        return json.loads(raw) if raw else None

    def length(self) -> int:
        """KEDA와 상태 API에서 사용할 현재 Redis LLEN 값을 반환합니다."""

        return int(self.redis.llen(self.queue_key))

    def clear(self) -> int:
        """테스트 Queue를 초기화하고 삭제 직전 작업 개수를 반환합니다."""

        current_length = self.length()
        self.redis.delete(self.queue_key)
        return current_length


def create_queue_service(settings: Settings | None = None) -> QueueService:
    """현재 환경 설정으로 Redis 클라이언트와 QueueService를 함께 구성합니다."""

    settings = settings or Settings()
    return QueueService(create_redis_client(settings), settings.redis_queue_key)
