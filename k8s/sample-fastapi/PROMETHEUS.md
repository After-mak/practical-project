# Sample FastAPI Prometheus 수집 및 검증 가이드

## 구성

| 대상 | Service | ServiceMonitor | 메트릭 주소 |
|---|---|---|---|
| FastAPI | `sample-fastapi` | `sample-fastapi` | `:8000/metrics` |
| Worker | `sample-worker-metrics` | `sample-worker` | `:9100/metrics` |

Prometheus는 `monitoring: prometheus` 라벨이 있는 Namespace의 같은 라벨을 가진
ServiceMonitor만 선택합니다. 따라서 Helm release 이름에 따른 `release` 라벨 차이에
영향받지 않습니다.

실제 애플리케이션에서 노출하는 Worker 메트릭 이름은 다음과 같습니다.

- `worker_processed_total`
- `sample_worker_active_jobs`
- `sample_worker_processing_duration_seconds_count`
- `sample_worker_processing_duration_seconds_sum`
- `sample_queue_processing_length`
- `sample_queue_dead_letter_length`
- `sample_queue_retry_total`
- `sample_queue_recovered_total`

## 1. 사전 확인

Prometheus Operator CRD와 Prometheus 리소스를 확인합니다.

```bash
kubectl get crd servicemonitors.monitoring.coreos.com
kubectl get prometheus -A
kubectl get pods -n prometheus
```

CRD가 없다면 먼저 Argo CD의 `prometheus-stack` Application을 Sync해야 합니다.

## 2. 리소스 적용

```bash
kubectl apply -f k8s/sample-fastapi/namespace.yaml
kubectl apply -f k8s/sample-fastapi/worker-service.yaml
kubectl apply -f k8s/sample-fastapi/fastapi-servicemonitor.yaml
kubectl apply -f k8s/sample-fastapi/worker-servicemonitor.yaml
```

Worker Deployment는 `replicas: 1`로 변경됐습니다. 매니페스트의 이미지 값은
자리표시자이므로 실제 재배포에는 `deploy.sh`를 사용하거나 현재 ECR 이미지 URI로
치환해야 합니다.

## 3. Kubernetes 연결 확인

```bash
kubectl -n sample-fastapi get deployment sample-worker
kubectl -n sample-fastapi rollout status deployment/sample-worker --timeout=180s
kubectl -n sample-fastapi get pods -l app.kubernetes.io/component=worker
kubectl -n sample-fastapi get svc,endpoints
kubectl -n sample-fastapi get servicemonitor --show-labels
```

예상 결과는 Worker `READY 1/1`, `sample-worker-metrics` Endpoint 존재,
ServiceMonitor 2개 존재입니다.

## 4. 메트릭 Endpoint 직접 확인

FastAPI:

```bash
kubectl -n sample-fastapi port-forward service/sample-fastapi 8000:8000
curl -s http://127.0.0.1:8000/metrics | grep '^sample_queue_length '
```

Worker:

```bash
kubectl -n sample-fastapi port-forward service/sample-worker-metrics 9100:9100
curl -s http://127.0.0.1:9100/metrics | grep -E \
  '^(worker_processed_total|sample_worker_active_jobs|sample_worker_processing_duration_seconds_)'
```

## 5. Prometheus Target 확인

Prometheus Service 이름을 확인하고 Port Forward를 실행합니다.

```bash
kubectl get svc -n prometheus
kubectl -n prometheus port-forward service/<PROMETHEUS_SERVICE_NAME> 9090:9090
```

브라우저에서 `http://127.0.0.1:9090/targets`를 열어 다음 Target이 `UP`인지
확인합니다.

- `sample-fastapi/sample-fastapi`
- `sample-fastapi/sample-worker`

Target이 보이지 않으면 다음 순서로 확인합니다.

```bash
kubectl get namespace sample-fastapi --show-labels
kubectl -n sample-fastapi get svc --show-labels
kubectl -n sample-fastapi get servicemonitor -o yaml
kubectl -n sample-fastapi get endpoints
kubectl -n prometheus logs deployment/prometheus-stack-kube-prom-operator
```

## 6. PromQL 및 Queue 통합 검증

Prometheus에서 다음 쿼리를 실행합니다.

```promql
max(sample_queue_length)
```

```promql
max(sample_queue_processing_length)
```

```promql
max(sample_queue_dead_letter_length)
```

```promql
sum(worker_processed_total)
```

```promql
sum(sample_worker_active_jobs)
```

```promql
sum(rate(sample_worker_processing_duration_seconds_count[5m]))
```

검증 순서는 다음과 같습니다.

1. Queue 초기 상태가 `0`인지 확인합니다.
2. FastAPI `/api/queue/join`으로 여러 작업을 등록합니다.
3. `max(sample_queue_length)`가 증가하는지 확인합니다.
4. Worker 로그에 `Processed job`이 기록되는지 확인합니다.
5. `sum(worker_processed_total)`이 증가하는지 확인합니다.
6. Queue가 다시 `0`으로 감소하는지 확인합니다.

## 완료 기준

- [ ] Worker Deployment `READY 1/1`
- [ ] Worker가 Queue 작업을 처리하고 Queue Length가 `0`으로 감소
- [ ] `sample-worker-metrics` Endpoint 생성
- [ ] FastAPI `/metrics` 직접 조회 성공
- [ ] Worker `9100/metrics` 직접 조회 성공
- [ ] FastAPI Target `UP`
- [ ] Worker Target `UP`
- [ ] `sample_queue_length` 값 변화 확인
- [ ] `worker_processed_total` 값 증가 확인
