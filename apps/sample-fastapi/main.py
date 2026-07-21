"""FinOps 부하 검증용 FastAPI API 애플리케이션입니다.

일반·CPU·메모리 부하 API와 Redis Queue 등록·조회 API를 제공하며, HTTP 및 Queue
메트릭을 Prometheus 형식으로 노출합니다. Queue 소비는 별도 ``worker.py``가 담당합니다.
"""

import logging
import random
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from metrics import (
    HTTP_ERRORS_TOTAL,
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    QUEUE_ENTER_TOTAL,
    QUEUE_FAILED_TOTAL,
    QUEUE_LENGTH,
    QUEUE_PROCESSED_TOTAL,
    render_metrics,
)
from queue_service import QueueService, create_queue_service


app = FastAPI(title="FinOps Sample FastAPI App")
logger = logging.getLogger("sample-fastapi")

# 애플리케이션 기본 QueueService입니다. 테스트에서는 FastAPI dependency override로 교체합니다.
queue_service = create_queue_service()


class QueueJoinRequest(BaseModel):
    """Queue에 등록할 작업 유형과 Worker에 전달할 Payload입니다."""

    job_type: str = Field(default="sample", min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


def get_queue_service() -> QueueService:
    """엔드포인트에 QueueService를 주입해 테스트 대역으로 교체할 수 있게 합니다."""

    return queue_service


def redis_unavailable(exc: RedisError) -> HTTPException:
    """Redis 연결 오류를 Secret이 포함되지 않은 HTTP 503으로 변환합니다."""

    logger.warning("Redis operation failed: %s", type(exc).__name__)
    return HTTPException(status_code=503, detail="Redis unavailable")


@app.middleware("http")
async def collect_http_metrics(request, call_next):
    """모든 API 요청의 상태 코드와 처리 시간을 Prometheus 메트릭에 기록합니다."""

    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        HTTP_REQUESTS_TOTAL.labels(request.method, request.url.path, "500").inc()
        HTTP_ERRORS_TOTAL.labels(request.method, request.url.path, "500").inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, request.url.path).observe(
            time.perf_counter() - started_at
        )
        raise

    status = str(response.status_code)
    HTTP_REQUESTS_TOTAL.labels(request.method, request.url.path, status).inc()
    if response.status_code >= 400:
        HTTP_ERRORS_TOTAL.labels(request.method, request.url.path, status).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(request.method, request.url.path).observe(
        time.perf_counter() - started_at
    )
    return response


@app.get("/health")
def health_check():
    """프로세스 생존 여부만 확인하는 Liveness Probe입니다."""

    return {"status": "ok", "service": "sample-fastapi"}


@app.get("/ready")
def readiness_check(service: QueueService = Depends(get_queue_service)):
    """Redis 연결까지 확인하는 Readiness Probe입니다."""

    try:
        service.ping()
    except RedisError as exc:
        raise redis_unavailable(exc) from exc
    return {"status": "ready", "redis": "ok"}


@app.get("/api/normal")
def normal():
    """추가 연산 없이 빠르게 응답해 정상 트래픽 기준선을 제공합니다."""

    return {"message": "normal request", "status": "success"}


@app.get("/api/cpu")
def cpu_load():
    """반복 제곱 연산으로 CPU 사용량 상승을 재현합니다."""

    result = 0
    for i in range(5_000_000):
        result += i * i
    return {"message": "cpu load generated", "result": result}


@app.get("/api/memory")
def memory_load():
    """요청 처리 중 약 100MB의 임시 문자열 데이터를 할당합니다."""

    data = ["x" * 1024 for _ in range(100_000)]
    return {"message": "memory load generated", "items": len(data)}


@app.get("/api/slow")
def slow():
    """2초 지연으로 느린 응답 상황을 의도적으로 재현합니다."""

    time.sleep(2)
    return {"message": "slow response"}


@app.get("/api/error")
def error():
    """장애·오류율 관측을 위해 약 30% 확률로 의도적인 HTTP 500을 반환합니다."""

    if random.random() < 0.3:
        raise HTTPException(status_code=500, detail="intentional random error")
    return {"message": "no error"}


@app.post("/api/queue/join")
def join_queue(
    request: QueueJoinRequest | None = None,
    service: QueueService = Depends(get_queue_service),
):
    """작업을 Redis Queue에 등록하고 작업 ID와 최신 Queue Length를 반환합니다."""

    request = request or QueueJoinRequest()
    try:
        job = service.enqueue(request.job_type, request.payload)
        current_queue_length = service.length()
    except RedisError as exc:
        QUEUE_FAILED_TOTAL.inc()
        raise redis_unavailable(exc) from exc

    QUEUE_ENTER_TOTAL.inc()
    QUEUE_LENGTH.set(current_queue_length)
    return {
        "message": "joined queue",
        "job_id": job["id"],
        "queue_length": current_queue_length,
    }


@app.post("/api/queue/process")
def process_queue(service: QueueService = Depends(get_queue_service)):
    """로컬 수동 검증을 위해 작업 하나를 즉시 소비하는 호환 API입니다.

    실제 배포에서는 별도 Queue Worker가 작업을 처리하며 k6 Scale-in 테스트도 이 API를
    호출하지 않고 Worker가 Queue를 비우는 과정을 상태 API로 관찰합니다.
    """

    try:
        job = service.dequeue(timeout=0)
        current_queue_length = service.length()
    except RedisError as exc:
        QUEUE_FAILED_TOTAL.inc()
        raise redis_unavailable(exc) from exc

    if job is not None:
        QUEUE_PROCESSED_TOTAL.inc()
    QUEUE_LENGTH.set(current_queue_length)
    return {
        "message": "processed queue" if job else "queue is empty",
        "job": job,
        "queue_length": current_queue_length,
    }


@app.get("/api/queue/status")
def queue_status(service: QueueService = Depends(get_queue_service)):
    """Redis LLEN 기준의 현재 공유 Queue Length를 반환합니다."""

    try:
        current_queue_length = service.length()
    except RedisError as exc:
        QUEUE_FAILED_TOTAL.inc()
        raise redis_unavailable(exc) from exc
    QUEUE_LENGTH.set(current_queue_length)
    return {"queue_length": current_queue_length}


@app.delete("/api/queue/reset")
def reset_queue(service: QueueService = Depends(get_queue_service)):
    """로컬·개발 환경의 Queue 테스트 데이터를 모두 초기화합니다."""

    try:
        deleted_items = service.clear()
    except RedisError as exc:
        QUEUE_FAILED_TOTAL.inc()
        raise redis_unavailable(exc) from exc
    QUEUE_LENGTH.set(0)
    return {"message": "queue reset", "deleted_items": deleted_items, "queue_length": 0}


@app.get("/metrics")
def metrics(service: QueueService = Depends(get_queue_service)):
    """Redis Queue Length를 갱신한 뒤 전체 API Prometheus 메트릭을 반환합니다."""

    try:
        QUEUE_LENGTH.set(service.length())
    except RedisError as exc:
        QUEUE_FAILED_TOTAL.inc()
        raise redis_unavailable(exc) from exc
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")
