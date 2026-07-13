# 샘플 애플리케이션 워크로드 요구사항

## 1. 문서 목적과 범위

이 문서는 Helm/GitOps 담당자와 KRR/Prometheus 담당자가 FastAPI 샘플 워크로드를 구성할 때 참고할 요구사항을 정의합니다. Kubernetes Manifest나 Helm Chart의 완성본은 이 문서의 범위가 아닙니다.

## 2. 공통 요구사항

### Namespace

권장 Namespace:

```text
finops-demo
```

### 공통 Label

모든 워크로드와 관련 Service에 다음 label을 적용합니다.

```yaml
labels:
  app: sample-fastapi
  project: finops-rightsizing
```

워크로드별 구분 label:

| 워크로드 | Label |
| --- | --- |
| `baseline-app` | `workload-type: baseline` |
| `overallocated-app` | `workload-type: overallocated` |
| `idle-app` | `workload-type: idle` |
| `spike-app` | `workload-type: spike` |

### 이미지

ECR 준비 후 다음 형식을 사용합니다.

```text
<ECR_REPOSITORY_URI>:<TAG>
```

예시:

```text
123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/sample-fastapi:<commit-sha>
```

재현성과 롤백을 위해 `latest`보다 commit SHA처럼 변경되지 않는 태그를 권장합니다.

### 포트와 Probe

```yaml
ports:
  - name: http
    containerPort: 8000

readinessProbe:
  httpGet:
    path: /health
    port: http

livenessProbe:
  httpGet:
    path: /health
    port: http
```

Probe의 `initialDelaySeconds`, `periodSeconds`, `timeoutSeconds` 및 failure threshold는 클러스터 환경에 맞게 Helm/GitOps 담당자가 결정합니다.

### Replica

초기 권장값은 모든 워크로드 1개입니다.

```text
baseline-app: 1
overallocated-app: 1
idle-app: 1
spike-app: 1
```

KEDA 대상 workload는 ScaledObject가 replica를 제어할 수 있도록 Deployment의 replica 관리 주체를 KEDA/GitOps 담당자 간에 합의해야 합니다.

## 3. 워크로드별 Resource 요구사항

### baseline-app

정상 트래픽의 CPU 및 메모리 기준선을 확보하는 워크로드입니다.

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "300m"
    memory: "256Mi"
```

추천 테스트: `normal-test.js`, `mixed-test.js`

### overallocated-app

실제 사용량보다 requests와 limits가 과도하게 설정된 상태를 재현합니다.

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

추천 테스트: `normal-test.js` 또는 낮은 강도의 `mixed-test.js`

### idle-app

Pod는 실행 중이지만 요청이 거의 없어 유휴 자원이 발생하는 상태를 재현합니다.

```yaml
resources:
  requests:
    cpu: "300m"
    memory: "256Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

추천 테스트: 부하 테스트를 실행하지 않고 health 요청만 간헐적으로 수행

### spike-app

평상시 사용량은 낮지만 특정 시점에 CPU 사용량이 급증하는 상태를 재현합니다.

```yaml
resources:
  requests:
    cpu: "200m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "512Mi"
```

추천 테스트: `cpu-spike-test.js`

## 4. Service 및 Ingress 요구사항

- Service는 컨테이너의 이름 있는 포트 `http` 또는 포트 `8000`을 대상으로 설정합니다.
- Ingress를 사용할 경우 `/health`, `/api/*`, `/metrics` 경로가 샘플 앱으로 전달되어야 합니다.
- 외부 부하 테스트 주소는 k6의 `BASE_URL`로 전달할 수 있어야 합니다.
- `/metrics`의 외부 공개 여부는 보안 정책에 따라 결정하고, 공개하지 않는 경우 Prometheus가 클러스터 내부에서 접근할 수 있어야 합니다.

## 5. Prometheus 요구사항

- Scrape 경로: `/metrics`
- Scrape 포트: `8000` 또는 Service의 `http` 포트
- 제공 메트릭: `sample_queue_length`
- 메트릭 유형: Gauge
- 의미: 해당 FastAPI 프로세스가 메모리에 보관하는 현재 Queue Length

Prometheus 담당자는 Pod 단위 값을 보존할 수 있도록 `pod`, `namespace`, `workload-type` label을 쿼리에서 구분할 수 있어야 합니다. KEDA에서 단일 값이 필요하면 `sum(sample_queue_length)` 등의 집계 방식을 KEDA 담당자와 합의합니다.

## 6. KEDA 연동 시 고려사항

- Queue 상태는 Redis나 외부 DB가 아니라 각 프로세스 메모리에 저장됩니다.
- replica가 2개 이상이면 요청이 분산되어 Pod마다 Queue Length가 다를 수 있습니다.
- Pod 재시작 시 해당 Pod의 Queue Length는 0으로 초기화됩니다.
- 초기 기능 검증은 replica 1개에서 시작하는 것을 권장합니다.
- Scale-Out 검증 시 Prometheus 쿼리의 Pod별 값 집계 방식을 명시해야 합니다.
- KEDA의 threshold, min/max replica, polling interval, cooldown period는 KEDA 담당자가 결정합니다.

이 제약은 초기 데모를 위한 것입니다. 공유 Queue와 정확한 소비 처리가 필요해지면 Redis 등 외부 저장소로 교체해야 합니다.

## 7. KRR 및 라이트사이징 관측 요구사항

KRR/Prometheus 담당자는 최소한 다음 데이터를 workload와 Pod 단위로 확인할 수 있어야 합니다.

- CPU usage와 CPU requests/limits
- Memory working set과 Memory requests/limits
- Pod replica 수와 재시작 횟수
- HTTP 요청량, 응답 시간 및 오류율(수집 구성이 있는 경우)
- `sample_queue_length`
- Node와 availability zone 정보

워크로드별 label을 유지해야 baseline, overallocated, idle, spike 데이터를 분리해 비교할 수 있습니다.

## 8. 담당자 인계 체크리스트

- [ ] Namespace가 `finops-demo`로 준비되어 있다.
- [ ] 공통 label과 `workload-type` label이 적용되어 있다.
- [ ] 워크로드별 requests/limits가 요구사항과 일치한다.
- [ ] 컨테이너 포트 8000과 Service target port가 연결되어 있다.
- [ ] `/health` Readiness/Liveness Probe가 설정되어 있다.
- [ ] ECR 이미지에 변경되지 않는 태그를 사용한다.
- [ ] Prometheus가 `/metrics`를 수집한다.
- [ ] `sample_queue_length`를 Pod 및 workload 단위로 조회할 수 있다.
- [ ] KEDA가 replica를 관리할 때 GitOps와 제어권 충돌이 없다.
- [ ] k6 실행 대상 `BASE_URL`이 준비되어 있다.
