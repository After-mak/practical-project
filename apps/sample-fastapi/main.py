import random
from threading import Lock
import time

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

# FastAPI 애플리케이션 객체입니다.
# title 값은 Swagger UI와 OpenAPI 문서에서 서비스 이름으로 표시됩니다.
app = FastAPI(title="FinOps Sample FastAPI App")

# Queue Length 기반 오토스케일링 테스트를 위한 인메모리 상태입니다.
# FastAPI의 동기 엔드포인트가 여러 스레드에서 실행될 수 있으므로 lock으로 보호합니다.
queue_length = 0
queue_lock = Lock()


@app.get("/health")
def health_check():
    # 로드밸런서, 컨테이너, Kubernetes 헬스체크에서 사용할 기본 상태 확인 API입니다.
    return {
        "status": "ok",
        "service": "sample-fastapi",
    }


@app.get("/api/normal")
def normal():
    # 일반적인 정상 요청을 빠르게 응답하는 샘플 API입니다.
    return {
        "message": "normal request",
        "status": "success",
    }


@app.get("/api/cpu")
def cpu_load():
    # CPU 사용량이 올라가는 상황을 만들기 위한 테스트 API입니다.
    # 부하 테스트나 오토스케일링 동작 확인에 사용할 수 있습니다.
    result = 0

    for i in range(5_000_000):
        result += i * i

    return {
        "message": "cpu load generated",
        "result": result,
    }


@app.get("/api/memory")
def memory_load():
    # 메모리를 일시적으로 사용하는 상황을 만들기 위한 테스트 API입니다.
    # 요청이 끝나면 함수 내부 변수는 정리 대상이 됩니다.
    data = ["x" * 1024 for _ in range(100_000)]

    return {
        "message": "memory load generated",
        "items": len(data),
    }


@app.get("/api/slow")
def slow():
    # 느린 응답 상황을 재현하기 위해 의도적으로 2초 대기합니다.
    time.sleep(2)

    return {
        "message": "slow response",
    }


@app.get("/api/error")
def error():
    # 장애 대응 테스트를 위해 약 30% 확률로 예외를 발생시킵니다.
    if random.random() < 0.3:
        raise Exception("random error occurred")

    return {
        "message": "no error",
    }


@app.post("/api/queue/join")
def join_queue():
    # 사용자가 대기열에 진입하는 상황을 재현합니다.
    global queue_length

    with queue_lock:
        queue_length += 1
        current_queue_length = queue_length

    return {
        "message": "joined queue",
        "queue_length": current_queue_length,
    }


@app.post("/api/queue/process")
def process_queue():
    # 대기열 항목을 하나 처리하되 Queue Length가 음수가 되지 않게 합니다.
    global queue_length

    with queue_lock:
        queue_length = max(0, queue_length - 1)
        current_queue_length = queue_length

    return {
        "message": "processed queue",
        "queue_length": current_queue_length,
    }


@app.get("/api/queue/status")
def queue_status():
    with queue_lock:
        current_queue_length = queue_length

    return {
        "queue_length": current_queue_length,
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    # Prometheus와 KEDA가 현재 Queue Length를 수집할 수 있게 노출합니다.
    with queue_lock:
        current_queue_length = queue_length

    content = (
        "# HELP sample_queue_length Current sample queue length\n"
        "# TYPE sample_queue_length gauge\n"
        f"sample_queue_length {current_queue_length}\n"
    )

    return PlainTextResponse(
        content=content,
        media_type="text/plain; version=0.0.4",
    )
