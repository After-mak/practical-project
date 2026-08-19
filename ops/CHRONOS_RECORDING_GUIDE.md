# Chronos-2 예측형 오토스케일링 녹화 준비 가이드

## 1. 녹화 목표

다음 순서를 영상으로 증명한다.

```text
Prometheus의 과거 Worker CPU 메트릭
→ Thanos Query
→ Chronos-2 향후 12분 예측
→ Prometheus 예측 메트릭
→ KEDA 선제적 Worker 확장
→ Pending Worker Pod
→ Karpenter NodeClaim 및 신규 Node
→ 실제 부하 발생 전에 Worker Ready
→ 실제 부하 처리
```

현재 모델은 `amazon/chronos-t5-small`이 아니라 **`amazon/chronos-2`와 `Chronos2Pipeline`**이다. 발표와 녹화에서는 **Chronos-2 기반 예측형 오토스케일링**이라고 설명한다.

## 2. 프로젝트 실제 리소스 정보

| 항목 | 실제 값 |
|---|---|
| EKS Cluster/권장 Context Alias | `project03-eks` |
| Worker Namespace | `sample-fastapi` |
| Chronos Namespace | `monitoring` |
| Chronos Deployment | `chronos-model` |
| Chronos Service | `chronos-model` |
| Chronos Container/Service Port | `8000` / `8000` |
| Chronos Metrics Path | `/metrics` |
| Chronos Model | `amazon/chronos-2` |
| 입력 데이터 | 최근 2시간 Worker 전체 CPU |
| 입력/예측 간격 | 60초 |
| 예측 길이 | 12개 시점 |
| 예측 Horizon | 12분 |
| KEDA ScaledObject | `sample-worker` |
| KEDA Scale Target | `sample-worker` |
| Worker Deployment | `sample-worker` |
| Worker Metrics Port | `9100` |
| Worker CPU/Memory Request | `361m` / `142Mi` |
| KEDA Polling/Cooldown | `5초` / `60초` |
| Reactive 최대 Replica | `15` |
| Predictive 최대 Replica | `3` |
| Karpenter NodePool | `worker-nodepool` |
| Karpenter EC2NodeClass | `worker-nodepool` |
| 허용 인스턴스 | `t3.small`, `t3.medium` |
| Capacity Type | On-Demand |
| Node 정리 | `WhenEmptyOrUnderutilized`, `30초` 후 통합 |

## 3. Chronos와 KEDA 메트릭

Chronos 입력 PromQL:

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

녹화에서 보여줄 주요 메트릭:

```text
chronos_predicted_cpu_cores
chronos_predicted_replicas
chronos_scaling_replicas
chronos_forecast_valid
chronos_forecast_timestamp_seconds
chronos_model_info
```

KEDA Chronos Trigger Query:

```promql
(
  max(
    chronos_scaling_replicas{
      exported_namespace="sample-fastapi",
      deployment="sample-worker"
    }
  )
  *
  max(
    chronos_forecast_valid{
      exported_namespace="sample-fastapi",
      deployment="sample-worker"
    }
  )
  *
  max(
    (
      time()
      -
      chronos_forecast_timestamp_seconds{
        exported_namespace="sample-fastapi",
        deployment="sample-worker"
      }
    ) < bool 120
  )
) or vector(0)
```

| KEDA 설정 | 값 |
|---|---:|
| Threshold | `1` |
| Activation Threshold | `0` |
| Min Replica | `1` |
| Predictive Max Replica | `3` |

## 4. 현재 안전 기본값과 녹화용 설정

GitOps 기본값은 테스트 종료 후 안전 상태로 복구되어 있다.

```yaml
# charts/chronos/values.yaml
forecast:
  mode: shadow

# charts/sample-fastapi/values.yaml
worker:
  autoscaling:
    mode: reactive
```

이 상태에서는 Chronos가 KEDA 확장을 발생시키지 않는다. 녹화 직전 GitOps에서 다음과 같이 전환해야 한다.

```yaml
# charts/chronos/values.yaml
forecast:
  mode: active

# charts/sample-fastapi/values.yaml
worker:
  autoscaling:
    mode: predictive
```

Argo CD 동기화 후 자동 점검 스크립트에서 다음을 확인한다.

```text
Chronos Mode = active
ScaledObject Trigger Names에 chronos 존재
ScaledObject Ready = True
sample-worker를 제어하는 HPA = 1개
```

## 5. kubeconfig 준비

현재 로컬 환경에 Context가 없다면 인프라 생성 후 다음 명령으로 등록한다.

```bash
aws eks update-kubeconfig \
  --region ap-northeast-2 \
  --name project03-eks \
  --alias project03-eks
```

확인:

```bash
kubectl config current-context
kubectl cluster-info
```

예상 Context:

```text
project03-eks
```

## 6. 더미 CPU 이력 준비

현재 Terraform에서 시딩 기능 기본값은 `false`다. 인프라 생성 시 다음 값을 전달해야 한다.

```powershell
terraform apply -var="enable_krr_demo_seed=true"
```

시딩 컨테이너는 `sample-worker`의 실제 Pod 이름을 조회한 뒤 `chronos-periodic-spike` 프로파일로 Prometheus TSDB Block을 만든다.

```text
20분 주기
0~8분   정상
8~12분  상승
12~16분 급증
16~20분 회복
```

시딩 로그 확인:

```bash
kubectl logs \
  -n prometheus \
  prometheus-prometheus-stack-kube-prom-prometheus-0 \
  -c krr-demo-seed
```

주의:

- Prometheus가 `sample-worker`보다 먼저 뜨면 현재 스크립트는 시딩을 건너뛸 수 있다.
- 시딩 로그에서 실제 Worker Pod를 찾았는지 반드시 확인한다.
- 더미 데이터는 미래로 계속 생성되지 않으므로 인프라 생성 후 2시간 안에 녹화를 진행하는 것이 안전하다.

## 7. 자동 점검 스크립트

파일:

```text
scripts/chronos-recording-check.sh
```

Linux, WSL 또는 Git Bash에서 실행 권한을 부여한다.

```bash
chmod +x scripts/chronos-recording-check.sh
```

기본 실행:

```bash
./scripts/chronos-recording-check.sh
```

스크립트는 클러스터를 변경하지 않고 다음 항목을 조회한다.

- Kubernetes Context 및 API 연결
- 필수 Namespace
- Chronos Deployment, Pod, Service
- Chronos 모델과 active 모드
- `/metrics` 주요 예측 메트릭
- KEDA ScaledObject, Trigger, Query, Threshold
- `sample-worker`를 제어하는 HPA 개수
- Worker Replica, Resource Request, Pending 상태
- Karpenter Controller, NodePool, EC2NodeClass Ready
- 현재 Node, NodeClaim 및 Allocatable
- 녹화 최종 입력값

환경에 따라 값을 덮어쓸 수 있다.

```bash
CONTEXT="project03-eks" \
EXPECTED_REPLICAS="3" \
EXPECTED_ADDITIONAL_NODES="1" \
./scripts/chronos-recording-check.sh
```

Shadow 상태를 관찰만 할 때:

```bash
REQUIRE_ACTIVE="false" ./scripts/chronos-recording-check.sh
```

녹화 직전에는 기본값인 `REQUIRE_ACTIVE=true`로 실행해야 한다.

## 8. 수동 확인 명령

### 8.1 Chronos

```bash
kubectl get deployment,service,pods \
  -n monitoring \
  -l app.kubernetes.io/name=chronos-model \
  -o wide
```

```bash
kubectl port-forward \
  -n monitoring \
  service/chronos-model \
  18000:8000
```

```bash
curl -s http://127.0.0.1:18000/metrics \
  | grep -E 'chronos_(predicted|scaling|forecast|model)'
```

### 8.2 KEDA와 Worker

```bash
kubectl get scaledobject,hpa -n sample-fastapi
kubectl describe scaledobject sample-worker -n sample-fastapi
kubectl get deployment sample-worker -n sample-fastapi -o wide
kubectl get pods -n sample-fastapi -o wide
```

### 8.3 Karpenter

```bash
kubectl get nodepool worker-nodepool
kubectl get ec2nodeclass worker-nodepool
kubectl get nodeclaim -w
kubectl get nodes -L karpenter.sh/nodepool,node.kubernetes.io/instance-type
kubectl get pods -n kube-system -l app.kubernetes.io/name=karpenter
```

## 9. Karpenter 발생 조건

현재 predictive 최대 Replica는 3이고 Worker 하나의 CPU Request는 `361m`이다.

```text
3개 Worker 총 CPU Request ≈ 1.083 core
```

기존 Node에 여유가 있으면 Worker 3개가 모두 기존 Node에 배치되어 Karpenter가 동작하지 않을 수 있다.

녹화 전 자동 점검 결과의 Node Allocatable과 현재 사용량을 확인한 뒤 다음 중 하나를 선택한다.

1. Predictive 최대 Replica를 높인다.
2. 녹화용 Worker CPU/Memory Request를 높인다.
3. 기존 Node의 남은 자원을 테스트용 Pod로 점유한다.

실제 조정값은 현재 Node의 남은 용량을 확인한 뒤 결정한다. 단순히 Replica 수만 높이면 불필요한 EC2가 여러 대 생성될 수 있으므로 사전 계산 없이 적용하지 않는다.

## 10. 녹화 터미널 구성

권장 화면:

| 터미널 | 명령 |
|---|---|
| 1 | `kubectl logs -n monitoring deployment/chronos-model -f` |
| 2 | `kubectl get hpa -n sample-fastapi -w` |
| 3 | `kubectl get pods -n sample-fastapi -o wide -w` |
| 4 | `kubectl get nodeclaim -w` 및 `kubectl get nodes -w` |
| 5 | Chronos `/metrics` 반복 조회 |
| 6 | k6 실행 |

메트릭 반복 조회 예시:

```bash
while true; do
  date '+%H:%M:%S'
  curl -s http://127.0.0.1:18000/metrics \
    | grep -E '^chronos_(predicted_replicas|scaling_replicas|forecast_valid|forecast_timestamp_seconds)'
  sleep 5
done
```

## 11. 녹화 시간 기록표

| 이벤트 | 계획 시각 | 실제 시각 |
|---|---|---|
| 녹화 시작 |  |  |
| Chronos 예측값 상승 |  |  |
| KEDA Desired Replica 상승 |  |  |
| Worker Pending |  |  |
| NodeClaim 생성 |  |  |
| 신규 Node Ready |  |  |
| Worker Ready |  |  |
| 실제 k6 부하 시작 |  |  |
| Queue 최고점 |  |  |
| Queue 소진 |  |  |
| Worker 축소 |  |  |
| 추가 Node 정리 |  |  |

핵심 성공 조건:

```text
신규 Node Ready 시각 < 실제 부하 시작 시각
Worker Ready 시각 < 실제 부하 시작 시각
```

## 12. 녹화 성공 순서

1. Queue Length가 0 또는 낮은 상태를 보여준다.
2. Worker Replica가 1개임을 보여준다.
3. `chronos_scaling_replicas`가 먼저 상승하는 것을 보여준다.
4. 실제 Queue 증가 전에 KEDA Desired Replica가 증가한다.
5. Worker Pod 일부가 Pending 상태가 된다.
6. Karpenter가 NodeClaim과 신규 Node를 생성한다.
7. Pending Worker가 신규 Node에서 Running/Ready 상태가 된다.
8. 실제 k6 부하를 시작한다.
9. 미리 준비된 Worker가 Queue를 처리한다.
10. 부하 종료 후 Worker와 Node가 축소되는 것을 보여준다.

## 13. 녹화 직전 체크리스트

- [ ] Context가 `project03-eks`이다.
- [ ] `sample-fastapi`, `monitoring`, `prometheus` Namespace가 존재한다.
- [ ] 더미 데이터 시딩 로그가 성공했다.
- [ ] Chronos 모델이 `amazon/chronos-2`다.
- [ ] Chronos가 `active` 모드다.
- [ ] `/metrics`에서 예측 메트릭이 조회된다.
- [ ] ScaledObject `sample-worker`가 Ready다.
- [ ] ScaledObject에 `queue`, `chronos` Trigger가 함께 존재한다.
- [ ] Worker를 제어하는 HPA가 하나뿐이다.
- [ ] Worker 초기 Replica가 1개다.
- [ ] Queue Length가 0 또는 낮다.
- [ ] Pending Worker가 없는 초기 상태다.
- [ ] NodePool과 EC2NodeClass가 Ready다.
- [ ] Karpenter Controller가 Ready다.
- [ ] 초기 Node와 NodeClaim 수를 기록했다.
- [ ] Worker 3개로 Pending이 발생하는지 계산했다.
- [ ] 예상 추가 Node 수를 기록했다.
- [ ] k6 대상 URL과 토큰을 확인했다.
- [ ] 녹화 터미널에서 AWS 계정, Redis Endpoint, Token을 가렸다.
- [ ] OBS 화면과 마이크를 테스트했다.

## 14. 녹화 종료 후 복구

GitOps 설정을 안전 기본값으로 돌린다.

```yaml
# charts/chronos/values.yaml
forecast:
  mode: shadow

# charts/sample-fastapi/values.yaml
worker:
  autoscaling:
    mode: reactive
```

복구 후 확인:

```bash
kubectl get scaledobject,hpa -n sample-fastapi
kubectl get pods -n sample-fastapi -o wide
kubectl get nodeclaim
kubectl get nodes
```
