"""Redis List를 사용하는 복구 가능한 공유 Queue 동작을 제공합니다."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis import Redis
from redis.exceptions import WatchError

from config import Settings
from redis_client import create_redis_client


@dataclass(frozen=True)
class ReservedJob:
    """Pending에서 Processing으로 원자적으로 이동한 작업과 원본 값을 묶습니다."""

    job: dict[str, Any]
    raw: str


class QueueService:
    """FastAPI와 여러 Worker가 동일한 Redis Queue를 사용하도록 캡슐화합니다.

    작업은 Pending List에 FIFO로 등록되고 LMOVE/BLMOVE를 통해 Processing List로
    원자적으로 이동합니다. Worker는 성공 시 ACK하고 실패 또는 visibility timeout 시
    재시도하며, 최대 재시도 횟수를 넘으면 Dead Letter Queue로 이동합니다.
    """

    def __init__(
        self,
        redis_client: Redis,
        queue_key: str,
        max_retries: int = 3,
        visibility_timeout_seconds: float = 60,
        completed_ttl_seconds: int = 86400,
    ):
        """사용할 Redis 클라이언트와 서비스별 Queue Key를 저장합니다."""

        self.redis = redis_client
        self.queue_key = queue_key
        self.processing_key = f"{queue_key}:processing"
        self.dead_letter_key = f"{queue_key}:dead-letter"
        self.leases_key = f"{queue_key}:leases"
        self.completed_key_prefix = f"{queue_key}:completed:"
        self.max_retries = max_retries
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.completed_ttl_seconds = completed_ttl_seconds

    def ping(self) -> bool:
        """Readiness Probe에서 사용할 Redis 연결 상태를 반환합니다."""

        return bool(self.redis.ping())

    def enqueue(self, job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """고유 ID와 등록 시각을 포함한 작업을 JSON으로 직렬화해 Queue에 추가합니다."""

        job = self._new_job(job_type, payload)
        self.redis.rpush(self.queue_key, json.dumps(job, separators=(",", ":")))
        return job

    def _new_job(
        self, job_type: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Queue 등록에 사용할 고유 작업 객체를 생성합니다."""

        return {
            "id": str(uuid4()),
            "type": job_type,
            "payload": payload or {},
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "attempts": 0,
        }

    def enqueue_many(
        self, count: int, job_type: str, payload: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """여러 작업을 하나의 Redis Transaction으로 등록해 부분 성공을 방지합니다."""

        jobs = [self._new_job(job_type, payload) for _ in range(count)]
        serialized = [json.dumps(job, separators=(",", ":")) for job in jobs]
        with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.rpush(self.queue_key, *serialized)
            pipeline.execute()
        return jobs

    def reserve(self, timeout: int = 1) -> ReservedJob | None:
        """가장 오래된 작업을 Pending에서 Processing으로 원자적으로 이동합니다.

        timeout이 0 이하이면 LMOVE, 양수이면 BLMOVE를 사용합니다. 이동 후 lease
        만료 시각을 ZSET에 기록해 Worker 비정상 종료 시 다른 Worker가 복구합니다.
        """

        if timeout <= 0:
            raw = self.redis.lmove(
                self.queue_key, self.processing_key, src="LEFT", dest="RIGHT"
            )
        else:
            raw = self.redis.blmove(
                self.queue_key,
                self.processing_key,
                timeout=timeout,
                src="LEFT",
                dest="RIGHT",
            )
        if not raw:
            return None

        job = json.loads(raw)
        lease_deadline = datetime.now(timezone.utc).timestamp() + self.visibility_timeout_seconds
        self.redis.zadd(self.leases_key, {raw: lease_deadline})
        return ReservedJob(job=job, raw=raw)

    def acknowledge(self, reservation: ReservedJob) -> bool:
        """처리 성공을 기록하고 Processing 및 lease에서 작업을 제거합니다."""

        completed_key = f"{self.completed_key_prefix}{reservation.job['id']}"
        with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.set(completed_key, "1", ex=self.completed_ttl_seconds)
            pipeline.lrem(self.processing_key, 1, reservation.raw)
            pipeline.zrem(self.leases_key, reservation.raw)
            _set_result, removed, _lease_removed = pipeline.execute()
        return bool(removed)

    def is_completed(self, job_id: str) -> bool:
        """이미 ACK된 작업 ID인지 확인해 복구 과정의 중복 처리를 억제합니다."""

        return bool(self.redis.exists(f"{self.completed_key_prefix}{job_id}"))

    def retry_or_dead_letter(
        self, reservation: ReservedJob, reason: str
    ) -> str:
        """실패 작업을 재시도하거나 최대 횟수 초과 시 DLQ로 이동합니다."""

        job = dict(reservation.job)
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["last_error"] = reason[:200]
        job["last_failed_at"] = datetime.now(timezone.utc).isoformat()
        destination = (
            self.queue_key
            if job["attempts"] <= self.max_retries
            else self.dead_letter_key
        )
        updated_raw = json.dumps(job, separators=(",", ":"))

        while True:
            with self.redis.pipeline() as pipeline:
                try:
                    pipeline.watch(self.processing_key)
                    if pipeline.lpos(self.processing_key, reservation.raw) is None:
                        pipeline.unwatch()
                        self.redis.zrem(self.leases_key, reservation.raw)
                        return "missing"
                    pipeline.multi()
                    pipeline.lrem(self.processing_key, 1, reservation.raw)
                    pipeline.zrem(self.leases_key, reservation.raw)
                    pipeline.rpush(destination, updated_raw)
                    pipeline.execute()
                    return "retry" if destination == self.queue_key else "dead-letter"
                except WatchError:
                    continue

    def ensure_processing_leases(self, now_timestamp: float) -> int:
        """reserve 직후 장애로 lease가 누락된 Processing 작업에 복구 기한을 부여합니다."""

        added = 0
        for raw in self.redis.lrange(self.processing_key, 0, -1):
            if self.redis.zscore(self.leases_key, raw) is None:
                self.redis.zadd(
                    self.leases_key,
                    {raw: now_timestamp + self.visibility_timeout_seconds},
                    nx=True,
                )
                added += 1
        return added

    def recover_stale(self, now_timestamp: float | None = None) -> dict[str, int]:
        """visibility timeout이 지난 Processing 작업을 재시도 또는 DLQ로 복구합니다."""

        now_timestamp = (
            datetime.now(timezone.utc).timestamp()
            if now_timestamp is None
            else now_timestamp
        )
        self.ensure_processing_leases(now_timestamp)
        stale_raw_values = self.redis.zrangebyscore(
            self.leases_key, min="-inf", max=now_timestamp
        )
        result = {"retried": 0, "dead_lettered": 0, "already_completed": 0}
        for raw in stale_raw_values:
            job = json.loads(raw)
            reservation = ReservedJob(job=job, raw=raw)
            if self.is_completed(job["id"]):
                with self.redis.pipeline(transaction=True) as pipeline:
                    pipeline.lrem(self.processing_key, 1, raw)
                    pipeline.zrem(self.leases_key, raw)
                    pipeline.execute()
                result["already_completed"] += 1
                continue
            destination = self.retry_or_dead_letter(
                reservation, "visibility timeout exceeded"
            )
            if destination == "retry":
                result["retried"] += 1
            elif destination == "dead-letter":
                result["dead_lettered"] += 1
        return result

    def dequeue(self, timeout: int = 1) -> dict[str, Any] | None:
        """호환 API용으로 작업을 reserve한 뒤 즉시 ACK하여 반환합니다."""

        reservation = self.reserve(timeout=timeout)
        if reservation is None:
            return None
        self.acknowledge(reservation)
        return reservation.job

    def length(self) -> int:
        """KEDA와 상태 API에서 사용할 현재 Redis LLEN 값을 반환합니다."""

        return int(self.redis.llen(self.queue_key))

    def processing_length(self) -> int:
        """현재 Worker가 처리 중이거나 복구를 기다리는 작업 수를 반환합니다."""

        return int(self.redis.llen(self.processing_key))

    def dead_letter_length(self) -> int:
        """최대 재시도 횟수를 초과한 작업 수를 반환합니다."""

        return int(self.redis.llen(self.dead_letter_key))

    def clear(self) -> int:
        """테스트 Queue 관련 List와 lease를 초기화하고 총 작업 개수를 반환합니다."""

        current_length = (
            self.length() + self.processing_length() + self.dead_letter_length()
        )
        completed_keys = list(
            self.redis.scan_iter(match=f"{self.completed_key_prefix}*")
        )
        self.redis.delete(
            self.queue_key,
            self.processing_key,
            self.dead_letter_key,
            self.leases_key,
            *completed_keys,
        )
        return current_length


def create_queue_service(settings: Settings | None = None) -> QueueService:
    """현재 환경 설정으로 Redis 클라이언트와 QueueService를 함께 구성합니다."""

    settings = settings or Settings()
    return QueueService(
        create_redis_client(settings),
        settings.redis_queue_key,
        max_retries=settings.queue_max_retries,
        visibility_timeout_seconds=settings.queue_visibility_timeout_seconds,
        completed_ttl_seconds=settings.queue_completed_ttl_seconds,
    )
