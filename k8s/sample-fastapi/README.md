# Sample FastAPI · Worker 정식 EKS 배포

이 디렉터리는 임시 테스트 Pod가 아니라 `sample-fastapi` Namespace에 유지되는 FastAPI와
Queue Worker Deployment를 관리합니다. API와 Worker는 같은 ECR 이미지를 사용하고 실행
명령만 다릅니다. Worker Metrics Service와 ServiceMonitor는 함께 관리하며,
실제 Prometheus Target 확인은
[`PROMETHEUS.md`](PROMETHEUS.md)를 따릅니다. KEDA 리소스는 아직 이 범위에 포함하지 않습니다.

## 1. 배포

프로젝트 루트에서 실행합니다.

```bash
export LOAD_TEST_TOKEN='Secret Manager에서 읽은 값'
bash k8s/sample-fastapi/deploy.sh
```

기본값은 ECR Tag `v0.1.0`, Namespace `sample-fastapi`, Queue Key
`dev:sample:queue`입니다. 다른 Tag가 필요하면 다음처럼 실행합니다.

```bash
LOAD_TEST_TOKEN='Secret에서 읽은 값' \
IMAGE_TAG=v0.1.1 \
bash k8s/sample-fastapi/deploy.sh
```

배포 스크립트는 다음 작업만 수행합니다.

```text
Sample FastAPI 전용 ECR 생성
Docker 이미지 Build와 Push
ElastiCache Endpoint ConfigMap 생성
FastAPI Deployment와 ClusterIP Service 배포
Worker Deployment 배포(기본 replicas=1)
Worker Metrics Service 배포
ServiceMonitor CRD가 있으면 FastAPI·Worker ServiceMonitor 배포
FastAPI·Worker Rollout 확인
```

## 2. FastAPI와 Queue 등록 검증

첫 번째 터미널에서 Port Forward를 유지합니다.

```bash
kubectl -n sample-fastapi port-forward service/sample-fastapi 8000:8000
```

두 번째 터미널에서 상태와 Queue를 확인합니다.

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
curl -s -X DELETE http://127.0.0.1:8000/api/queue/reset \
  -H "X-Test-Token: ${LOAD_TEST_TOKEN}"
```

Worker가 1개이고 Ready인지 확인한 후 작업 3개를 등록합니다. Worker가 즉시 작업을
가져가므로 Queue Length는 일시적으로 증가했다가 다시 0으로 감소할 수 있습니다.

```bash
kubectl -n sample-fastapi get deployment sample-worker

for number in 1 2 3; do
  curl -s -X POST http://127.0.0.1:8000/api/queue/join \
    -H 'Content-Type: application/json' \
    -H "X-Test-Token: ${LOAD_TEST_TOKEN}" \
    -d "{\"job_type\":\"elasticache-test-${number}\",\"payload\":{\"id\":${number},\"processing_seconds\":5}}"
  echo
done

curl -s http://127.0.0.1:8000/api/queue/status
curl -s http://127.0.0.1:8000/metrics | grep '^sample_queue_length '
```

정상 결과는 Queue API와 `sample_queue_length`가 증가한 뒤 Worker 처리에 따라 다시
`0`으로 감소하는 것입니다.

Redis에 저장된 실제 Queue Key와 Length도 TLS로 확인합니다.

```bash
REDIS_HOST=$(kubectl -n sample-fastapi get configmap sample-fastapi-config \
  -o jsonpath='{.data.REDIS_HOST}')

kubectl -n sample-fastapi run redis-llen-before \
  --rm -i --restart=Never --image=redis:7-alpine -- \
  redis-cli -h "${REDIS_HOST}" -p 6379 --tls LLEN dev:sample:queue
```

Worker 처리 중이면 `0` 이상의 값이 표시되며, 최종적으로 `0`이 되어야 합니다.

## 3. Worker 처리 검증

Worker Deployment는 배포 시점부터 1개를 유지합니다.

```bash
kubectl -n sample-fastapi rollout status deployment/sample-worker --timeout=180s
kubectl -n sample-fastapi logs deployment/sample-worker -f
```

`Processed job` 로그가 3개 나타나면 `Ctrl+C`로 로그 조회만 종료합니다.

```bash
curl -s http://127.0.0.1:8000/api/queue/status
curl -s http://127.0.0.1:8000/metrics | grep '^sample_queue_length '
```

Redis의 최종 Queue Length도 확인합니다.

```bash
kubectl -n sample-fastapi run redis-llen-after \
  --rm -i --restart=Never --image=redis:7-alpine -- \
  redis-cli -h "${REDIS_HOST}" -p 6379 --tls LLEN dev:sample:queue
```

세 결과 모두 `0`이어야 합니다.

Worker 메트릭은 별도 터미널에서 Port Forward한 뒤 확인합니다.

```bash
kubectl -n sample-fastapi port-forward service/sample-worker-metrics 9100:9100
```

```bash
curl -s http://127.0.0.1:9100/metrics | grep '^worker_processed_total '
```

3개를 처리했다면 `worker_processed_total 3.0`이 표시됩니다.

## 4. 상태 확인

```bash
kubectl -n sample-fastapi get deployment,pod,service,configmap
kubectl -n sample-fastapi logs deployment/sample-fastapi
kubectl -n sample-fastapi logs deployment/sample-worker
```

ConfigMap에는 Endpoint와 일반 연결 설정만 저장하며 Password나 Auth Token은 넣지 않습니다.
`LOAD_TEST_TOKEN`은 `sample-fastapi-load-test` Kubernetes Secret으로만 주입합니다.
Namespace와 Deployment는 통합 테스트 후에도 유지되는 정식 배포 리소스입니다.

## 5. KRR 워크로드 시나리오

`workload-scenarios.yaml`은 기본 배포와 분리된 Baseline·Overallocated·Idle·Spike
Deployment/Service를 제공합니다. `yq`로 필요한 `workload-type`만 선택한 뒤 실제 ECR
이미지로 치환해 적용합니다.

```bash
export WORKLOAD_TYPE=overallocated
yq 'select(.metadata.labels."workload-type" == strenv(WORKLOAD_TYPE))' \
  k8s/sample-fastapi/workload-scenarios.yaml \
  | sed "s|sample-fastapi:replace-me|${IMAGE_URI}|g" \
  | kubectl apply -f -
```

각 Deployment에는 `workload-type` 라벨이 있으며 실행 방법과 관측 기록은
[`k6/README.md`](../../k6/README.md)를 따릅니다.

## 6. 복구 가능한 Queue

Worker는 Pending 작업을 Redis `LMOVE/BLMOVE`로 Processing Queue에 원자적으로 옮깁니다.
성공하면 ACK로 제거하고, 실패 또는 visibility timeout이면 재시도한 뒤 최대 횟수를
초과하면 Dead Letter Queue로 이동합니다.

```text
dev:sample:queue
dev:sample:queue:processing
dev:sample:queue:leases
dev:sample:queue:dead-letter
```

이 구조는 작업 유실을 방지하는 at-least-once 처리입니다. 처리 완료 직후 ACK 전에
프로세스가 강제 종료되는 극단 상황에서는 동일 작업 ID가 재전달될 수 있으므로 실제
업무 Side Effect도 작업 ID 기반 멱등 처리가 필요합니다.
