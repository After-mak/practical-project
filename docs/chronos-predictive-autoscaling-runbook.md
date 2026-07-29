# Chronos-2 기반 선제 오토스케일링 Runbook

## 검증 범위

2026-07-28에 다음 반응형 흐름은 실제 EKS에서 검증하고 녹화했습니다.

```text
k6 Queue 부하
→ Redis Queue Length
→ Prometheus
→ KEDA
→ sample-worker 확장
→ Pending Pod
→ Karpenter NodeClaim
→ 신규 Node
→ Queue 소진
→ Pod·Node 축소
```

이번 작업은 기존 Queue Trigger를 Fallback으로 유지하면서 그 앞에 Chronos 예측
Trigger를 추가합니다.

```text
Thanos 과거 CPU
→ Chronos 예측
→ chronos_scaling_replicas
→ KEDA
→ 부하 전 Worker·Node 준비
```

## 배포 계약

| 항목 | 값 |
|---|---|
| Chronos Namespace | `monitoring` |
| Chronos Service | `chronos-model:8000` |
| Chronos 모델/Pipeline | `amazon/chronos-2` / `Chronos2Pipeline` |
| 대상 Namespace | `sample-fastapi` |
| 대상 Deployment | `sample-worker` |
| Queue | `dev:sample:queue` |
| 기본/테스트 최대 Replica | `1/3` |
| 예측 실행 주기/TTL | `60s/120s` |
| 예측 범위 | 향후 12분 |

Chronos는 기존 FinOps 계약인
`GET /predict/{namespace}/{deployment}`와 Prometheus `/metrics`를 함께 제공합니다.

## 1. 사전 상태 확인

```bash
kubectl get scaledobject,hpa -n sample-fastapi
kubectl get nodepool,ec2nodeclass,nodeclaim
kubectl get pods -n kube-system -l app.kubernetes.io/name=karpenter
kubectl get applications -n argocd
```

기본 GitOps 값은 안전한 `reactive`와 `shadow`입니다.

```yaml
# charts/sample-fastapi/values.yaml
worker:
  autoscaling:
    mode: reactive

# charts/chronos/values.yaml
forecast:
  mode: shadow
```

## 2. Thanos S3 영속성

Prometheus 로컬 보존은 2일이고 Thanos S3는 30일 Lifecycle을 사용합니다.
`infra/terraform/init`의 Thanos 버킷에는 `prevent_destroy`가 적용되어 있으므로 dev
EKS를 삭제할 때 init Root Module을 삭제 대상에 포함하지 않습니다.

### 데이터 생성

현재 Worker Pod 이름을 사용해 반복 Spike OpenMetrics를 생성합니다.

```bash
POD_NAME=$(kubectl get pods -n sample-fastapi \
  -l app.kubernetes.io/component=worker \
  -o jsonpath='{.items[0].metadata.name}')

python3 finops/scripts/generate_krr_dummy_history.py \
  --namespace sample-fastapi \
  --deployment sample-worker \
  --pod "$POD_NAME" \
  --days 2 \
  --profile chronos-periodic-spike \
  --output /tmp/sample-worker-chronos.om
```

OpenMetrics는 Prometheus TSDB Block으로 변환되어야 하며 JSON/CSV를 S3에 직접
업로드하지 않습니다. 기존 `krr-demo-seed` initContainer의 promtool 절차를
재사용합니다.

### 업로드 확인

```bash
kubectl logs -n prometheus \
  prometheus-prometheus-stack-kube-prom-prometheus-0 \
  -c thanos-sidecar

aws s3api list-objects-v2 \
  --bucket project03-thanos-metrics-83154bf5 \
  --max-items 20
```

S3 Block의 `meta.json`, `index`, `chunks`를 확인한 뒤 인프라를 삭제합니다. 테스트
직후 아직 Block으로 압축되지 않은 Prometheus Head 데이터는 유실될 수 있으므로
Thanos Query에서 과거 범위를 조회한 후 삭제합니다.

### 재생성 후 확인

```bash
kubectl get pods -n prometheus
kubectl port-forward -n prometheus service/thanos-query 19090:9090
```

```promql
sum(
  rate(
    container_cpu_usage_seconds_total{
      namespace="sample-fastapi",
      pod=~"sample-worker-.*",
      container="worker"
    }[5m]
  )
)
```

인프라 삭제 전 Timestamp가 Thanos Query에서 다시 보이면 영속성 검증 성공입니다.

## 3. Fake Metric 계약 테스트

Chronos 모델을 연결하기 전에 Chronos Chart의 테스트 옵션으로 KEDA 계산을
검증합니다.

```yaml
# charts/chronos/values.yaml
forecast:
  mode: active
  fakeReplicas: "3"
```

```text
chronos_scaling_replicas{namespace="sample-fastapi",deployment="sample-worker"} 3
chronos_forecast_valid{namespace="sample-fastapi",deployment="sample-worker"} 1
chronos_forecast_timestamp_seconds{namespace="sample-fastapi",deployment="sample-worker"} <현재 Unix 시각>
```

GitOps 값을 `worker.autoscaling.mode=predictive`로 변경합니다.

성공 조건:

- Predictive ScaledObject `Ready=True`
- HPA Desired Replica 3
- Queue가 0이어도 Worker 3개
- 최대 Replica 3을 초과하지 않음
- 메트릭 만료 후 HPA stabilization을 거쳐 1개로 축소

## 4. Shadow Mode

Chronos는 기본적으로 Shadow Mode로 배포됩니다. Fake 테스트가 끝나면
`fakeReplicas: ""`로 되돌린 후 Shadow Mode를 시작합니다.

```bash
kubectl get pods,svc,servicemonitor -n monitoring
kubectl logs -n monitoring deployment/chronos-model -f
kubectl port-forward -n monitoring service/chronos-model 18000:8000

curl http://127.0.0.1:18000/health/live
curl http://127.0.0.1:18000/health/ready
curl http://127.0.0.1:18000/predict/sample-fastapi/sample-worker
curl http://127.0.0.1:18000/metrics
```

Shadow Mode 성공 조건:

- `/health/live`의 `model_id=amazon/chronos-2`
- `chronos_model_info{model_id="amazon/chronos-2"} 1`
- Thanos Query 성공
- 예측 Timestamp가 60초마다 갱신
- `chronos_forecast_valid=1`
- `chronos_predicted_replicas` 출력
- `chronos_scaling_replicas=0`
- Worker Replica는 Chronos 때문에 변하지 않음

## 5. Active Mode

두 GitOps 값을 함께 변경합니다.

```yaml
# charts/chronos/values.yaml
forecast:
  mode: active

# charts/sample-fastapi/values.yaml
worker:
  autoscaling:
    mode: predictive
```

```bash
kubectl get hpa -n sample-fastapi -w
kubectl get pods -n sample-fastapi -o wide -w
kubectl get nodeclaim -w
kubectl get nodes -w
```

Chronos 신호가 3이면 KEDA는 Queue Trigger와 Chronos Trigger가 계산한 값 중 큰
Desired Replica를 사용합니다. TTL 초과 또는 예측 오류 시 Chronos PromQL은 0을
반환하고 실제 Queue Trigger만 남습니다.

## 6. 전체 선제형 E2E

시간축을 UTC로 기록합니다.

| 시각 | 이벤트 |
|---|---|
| T1 | Chronos 예측 생성 |
| T2 | `chronos_scaling_replicas` 증가 |
| T3 | KEDA Desired Replica 증가 |
| T4 | Worker 생성 |
| T5 | Worker Pending |
| T6 | NodeClaim 생성 |
| T7 | 신규 Node Ready |
| T8 | Worker Ready |
| T9 | 실제 k6 Spike 시작 |
| T10 | Queue 최고점 |
| T11 | Queue 소진 |
| T12 | Worker Scale-in |
| T13 | Node 삭제 |

성공 조건:

```text
T7 < T9
T8 < T9
```

KEDA·Queue 기준 테스트:

```bash
k6 run \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e LOAD_TEST_TOKEN="$LOAD_TEST_TOKEN" \
  -e QUEUE_RATE=20 \
  -e LOAD_DURATION=30s \
  -e DRAIN_DURATION=8m \
  k6/queue-scale-test.js
```

강한 Karpenter 압력:

```bash
k6 run \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e LOAD_TEST_TOKEN="$LOAD_TEST_TOKEN" \
  -e QUEUE_RATE=100 \
  -e TEST_DURATION=5m \
  k6/karpenter-stress.js
```

## 7. A/B 비교

| A: 반응형 | B: 선제형 |
|---|---|
| Chronos `disabled` | Chronos `active` |
| Autoscaling `reactive` | Autoscaling `predictive` |
| Queue Trigger | Chronos + Queue Trigger |

두 실행은 이미지 태그, Worker Requests, 최대 Replica, 초기 Node 수, Queue 초기
상태와 k6 옵션을 동일하게 맞춥니다.

비교 항목:

- Worker/Node Ready 시각
- Pending Pod 지속시간
- Queue 최고 길이와 소진 시간
- HTTP 실패율과 p95
- 선제 Pod·Node 유휴 시간
- 추가 비용

## 8. 테스트 종료

검증 후 기본 안전 설정으로 복구합니다.

```yaml
forecast:
  mode: shadow

worker:
  autoscaling:
    mode: reactive
```
