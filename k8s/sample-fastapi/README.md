# Sample FastAPI · Worker 정식 EKS 배포

이 디렉터리는 임시 테스트 Pod가 아니라 `sample-fastapi` Namespace에 유지되는 FastAPI와
Queue Worker Deployment를 관리합니다. API와 Worker는 같은 ECR 이미지를 사용하고 실행
명령만 다릅니다. Prometheus Target과 KEDA 리소스는 현재 범위에 포함하지 않습니다.

## 1. 배포

프로젝트 루트에서 실행합니다.

```bash
bash k8s/sample-fastapi/deploy.sh
```

기본값은 ECR Tag `v0.1.0`, Namespace `sample-fastapi`, Queue Key
`dev:sample:queue`입니다. 다른 Tag가 필요하면 다음처럼 실행합니다.

```bash
IMAGE_TAG=v0.1.1 bash k8s/sample-fastapi/deploy.sh
```

배포 스크립트는 다음 작업만 수행합니다.

```text
Sample FastAPI 전용 ECR 생성
Docker 이미지 Build와 Push
ElastiCache Endpoint ConfigMap 생성
FastAPI Deployment와 ClusterIP Service 배포
Worker Deployment 배포(초기 replicas=0)
FastAPI Rollout 확인
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
curl -s -X DELETE http://127.0.0.1:8000/api/queue/reset
```

Worker가 0개인지 확인한 후 작업 3개를 등록합니다.

```bash
kubectl -n sample-fastapi get deployment sample-worker

for number in 1 2 3; do
  curl -s -X POST http://127.0.0.1:8000/api/queue/join \
    -H 'Content-Type: application/json' \
    -d "{\"job_type\":\"elasticache-test-${number}\",\"payload\":{\"id\":${number},\"processing_seconds\":1}}"
  echo
done

curl -s http://127.0.0.1:8000/api/queue/status
curl -s http://127.0.0.1:8000/metrics | grep '^sample_queue_length '
```

정상 결과는 Queue API와 `sample_queue_length` 모두 `3`입니다.

Redis에 저장된 실제 Queue Key와 Length도 TLS로 확인합니다.

```bash
REDIS_HOST=$(kubectl -n sample-fastapi get configmap sample-fastapi-config \
  -o jsonpath='{.data.REDIS_HOST}')

kubectl -n sample-fastapi run redis-llen-before \
  --rm -i --restart=Never --image=redis:7-alpine -- \
  redis-cli -h "${REDIS_HOST}" -p 6379 --tls LLEN dev:sample:queue
```

예상 결과는 `(integer) 3`입니다.

## 3. Worker 처리 검증

Queue Length 3을 확인한 후 정식 Worker Deployment를 1개로 확장합니다.

```bash
kubectl -n sample-fastapi scale deployment/sample-worker --replicas=1
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
kubectl -n sample-fastapi port-forward deployment/sample-worker 9100:9100
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
Namespace와 Deployment는 통합 테스트 후에도 유지되는 정식 배포 리소스입니다.
