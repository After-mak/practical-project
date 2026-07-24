# Sample FastAPI Grafana 검증·발표 시나리오

Grafana의 `FinOps / Sample FastAPI Workload` 대시보드는 Queue 증가부터 KEDA Worker
Scale-out·Queue 소진·Scale-in까지 한 화면에서 확인하기 위한 전용 대시보드입니다.

## 패널

| 패널 | 확인 내용 |
|---|---|
| Redis Queue State | Pending, Processing, Dead Letter Queue |
| Worker Deployment Replicas | Worker Deployment 현재/Spec Replica |
| KEDA HPA Current vs Desired | KEDA가 계산한 Current/Desired Replica |
| Worker Queue Events | 처리율, 재시도, 장애 복구, DLQ 이동 |
| Sample Pod CPU Usage | FastAPI·Worker Pod별 CPU 사용량 |
| Sample Pod Memory Working Set | FastAPI·Worker Pod별 Memory 사용량 |

모든 PromQL은 `namespace="sample-fastapi"`로 범위를 제한합니다. HPA 패널은
`keda-hpa-sample-worker`만 조회합니다.

## 사전 확인

```bash
kubectl -n prometheus get pods
kubectl -n sample-fastapi get servicemonitor,service,endpoints
kubectl -n sample-fastapi get scaledobject,hpa
```

Prometheus Target에서 다음 두 Target이 `UP`이어야 합니다.

- `sample-fastapi`
- `sample-worker`

## 발표용 Queue/KEDA 흐름

FastAPI Service를 Port Forward하고 Load Test Token을 환경변수로 준비합니다.

```bash
kubectl -n sample-fastapi port-forward service/sample-fastapi 8000:80
export LOAD_TEST_TOKEN='Kubernetes Secret에서 읽은 값'
```

Queue/KEDA 부하를 실행합니다.

```bash
k6 run \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e LOAD_TEST_TOKEN="$LOAD_TEST_TOKEN" \
  -e QUEUE_RATE=20 \
  -e LOAD_DURATION=30s \
  -e DRAIN_DURATION=8m \
  k6/queue-scale-test.js
```

대시보드에서 다음 순서를 확인합니다.

1. Pending Queue가 KEDA Threshold 5를 초과
2. HPA Desired Replica가 1에서 최대 3으로 증가
3. Worker Deployment Replica가 1에서 3으로 증가
4. Processing 작업과 Worker 처리율 증가
5. Pending과 Processing이 0으로 감소
6. DLQ는 계속 0 유지
7. HPA 안정화 시간 이후 Desired와 Worker가 1로 감소

## PromQL 직접 검증

```promql
max(sample_queue_length{namespace="sample-fastapi",service="sample-fastapi"}) or vector(0)
```

```promql
max(sample_queue_processing_length{namespace="sample-fastapi",service="sample-fastapi"}) or vector(0)
```

```promql
max(sample_queue_dead_letter_length{namespace="sample-fastapi",service="sample-fastapi"}) or vector(0)
```

```promql
kube_horizontalpodautoscaler_status_current_replicas{
  namespace="sample-fastapi",
  horizontalpodautoscaler="keda-hpa-sample-worker"
}
```

```promql
kube_horizontalpodautoscaler_status_desired_replicas{
  namespace="sample-fastapi",
  horizontalpodautoscaler="keda-hpa-sample-worker"
}
```

```promql
kube_deployment_status_replicas{
  namespace="sample-fastapi",
  deployment="sample-worker"
}
```

```promql
sum(rate(container_cpu_usage_seconds_total{
  namespace="sample-fastapi",
  pod=~"sample-(fastapi|worker)-.*",
  container!="",
  container!="POD"
}[5m])) by (pod)
```

```promql
sum(container_memory_working_set_bytes{
  namespace="sample-fastapi",
  pod=~"sample-(fastapi|worker)-.*",
  container!="",
  container!="POD"
}) by (pod)
```

## 완료 기준

- Queue·Worker·HPA·CPU·Memory 패널에 데이터 표시
- Pending/Processing 최종 0
- DLQ 최종 0
- Worker 1 → 3 → 1 변화 표시
- HPA Current/Desired와 실제 Deployment Replica 흐름 일치
- Grafana 패널 Query가 다른 Namespace의 워크로드를 포함하지 않음
- k6 HTTP 실패율 0% 및 Check 성공
