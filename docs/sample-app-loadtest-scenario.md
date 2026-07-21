# 샘플 앱 및 부하 테스트 실행 시나리오

## 1. 문서 목적

이 문서는 FinOps 기반 Kubernetes 리소스 라이트사이징 검증에 사용하는 FastAPI 샘플 앱과 k6 부하 테스트의 실행 방법을 설명합니다. Prometheus/Grafana, KRR, KEDA, Karpenter, Chronos-2 담당자가 동일한 워크로드를 재현하고 결과를 비교하는 기준으로 사용합니다.

이 저장소에서는 샘플 애플리케이션과 부하 생성 도구만 제공합니다. EKS, ECR, Prometheus, KEDA, Karpenter, Helm 및 Argo CD 구성은 각 담당 영역에서 진행합니다.

## 2. 샘플 앱 목적

샘플 앱은 다음 상황을 의도적으로 재현합니다.

- 정상적인 저지연 API 요청
- CPU 사용량 급증
- 일시적인 메모리 사용량 증가
- 느린 응답과 간헐적인 오류
- Queue Length 증가 및 감소
- Prometheus 형식의 Queue Length 메트릭 노출

Queue 상태는 프로세스 메모리에 저장됩니다. Pod가 재시작되거나 여러 replica를 사용하면 Queue Length가 초기화되거나 Pod별로 서로 다른 값을 가질 수 있습니다. 초기 KEDA 연동 검증용이며 실제 공유 Queue를 대신하지 않습니다.

## 3. API 목록

| Method | Endpoint | 목적 |
| --- | --- | --- |
| `GET` | `/health` | Liveness/Readiness 및 서비스 상태 확인 |
| `GET` | `/api/normal` | 정상 기준 요청 생성 |
| `GET` | `/api/cpu` | CPU 집약적인 계산 수행 |
| `GET` | `/api/memory` | 일시적인 메모리 부하 생성 |
| `GET` | `/api/slow` | 2초 지연 응답 생성 |
| `GET` | `/api/error` | 약 30% 확률의 HTTP 500 생성 |
| `POST` | `/api/queue/join` | Queue Length 1 증가 |
| `POST` | `/api/queue/process` | Queue Length 1 감소, 최솟값 0 |
| `GET` | `/api/queue/status` | 현재 Queue Length 조회 |
| `GET` | `/metrics` | `sample_queue_length` Prometheus 메트릭 조회 |

`/metrics` 응답 예시:

```text
# HELP sample_queue_length Current sample queue length
# TYPE sample_queue_length gauge
sample_queue_length 9
```

## 4. k6 테스트 목록

| 파일 | 목적 | 주요 대상 API |
| --- | --- | --- |
| `smoke.js` | 배포 직후 핵심 API와 메트릭 확인 | `/health`, `/ready`, `/api/normal`, `/metrics` |
| `normal-load.js` | 정상 트래픽 기준선 생성 | `/api/normal` |
| `cpu-load.js` | CPU 사용량 급증 재현 | `/api/cpu` |
| `memory-load.js` | 메모리 사용량 증가 재현 | `/api/memory` |
| `queue-scale-out.js` | 일정 도착률로 Redis Queue 증가 | `/api/queue/join` |
| `queue-scale-in.js` | Worker의 Queue 소진 여부 확인 | `/api/queue/status` |
| `soak.js` | 장시간 안정성과 누수 확인 | `/api/normal` |
| `karpenter-stress.js` | KEDA Pod 및 Karpenter Node 확장 압력 생성 | `/api/queue/join` |

모든 신규 테스트는 Threshold를 포함하며 기준을 만족하지 못하면 0이 아닌 종료 코드로 실패합니다.

## 5. 로컬 실행 방법

### 5.1 Docker 이미지 빌드 및 실행

프로젝트 루트에서 실행합니다.

```bash
docker build -t sample-fastapi:local apps/sample-fastapi
docker run --rm --name sample-fastapi -p 8000:8000 sample-fastapi:local
```

다른 터미널에서 기본 상태를 확인합니다.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/queue/status
curl http://localhost:8000/metrics
```

Windows PowerShell에서는 `curl` 대신 `curl.exe`를 사용할 수 있습니다.

### 5.2 Queue API 동작 확인

```bash
curl -X POST http://localhost:8000/api/queue/join
curl -X POST http://localhost:8000/api/queue/join
curl http://localhost:8000/api/queue/status
curl http://localhost:8000/metrics
curl -X POST http://localhost:8000/api/queue/process
curl http://localhost:8000/api/queue/status
```

확인 기준:

- join 요청마다 `queue_length`가 1 증가합니다.
- process 요청마다 1 감소하며 0보다 작아지지 않습니다.
- status 응답과 `/metrics`의 `sample_queue_length` 값이 같습니다.

### 5.3 k6 실행

```bash
k6 run k6/smoke.js
k6 run k6/normal-load.js
k6 run k6/cpu-load.js
k6 run k6/memory-load.js
k6 run -e QUEUE_RATE=20 -e TEST_DURATION=2m k6/queue-scale-out.js
k6 run -e TEST_DURATION=2m k6/queue-scale-in.js
```

메모리, CPU 및 Queue 테스트는 시스템 부하를 높일 수 있으므로 한 번에 하나씩 실행합니다.

## 6. EKS/Ingress 환경 실행 방법

`BASE_URL`에 Ingress 또는 서비스 접근 주소를 전달합니다. 주소 끝에는 `/`를 붙이지 않습니다.

```bash
k6 run -e BASE_URL=http://<ingress-url> k6/smoke.js
k6 run -e BASE_URL=http://<ingress-url> k6/normal-load.js
k6 run -e BASE_URL=http://<ingress-url> k6/cpu-load.js
k6 run -e BASE_URL=http://<ingress-url> -e QUEUE_RATE=20 k6/queue-scale-out.js
k6 run -e BASE_URL=http://<ingress-url> k6/queue-scale-in.js
```

실행 전 다음 항목을 확인합니다.

- `GET /health`가 HTTP 200을 반환하는지
- 테스트 대상 workload와 Ingress 라우팅이 일치하는지
- Prometheus가 `/metrics`를 수집하고 있는지
- 다른 팀원의 측정 또는 데모와 시간이 겹치지 않는지

## 7. 워크로드별 추천 테스트

| 워크로드 | 목적 | 추천 테스트 |
| --- | --- | --- |
| `baseline-app` | 정상 사용량의 기준선 확보 | `normal-load.js` |
| `overallocated-app` | 실제 사용량 대비 과도한 requests 재현 | 낮은 VU의 `normal-load.js` 또는 `soak.js` |
| `idle-app` | 실행 중이지만 트래픽이 거의 없는 상태 재현 | k6를 실행하지 않거나 간헐적인 health 요청만 수행 |
| `spike-app` | 특정 시점의 CPU 급증 재현 | `cpu-load.js` |

Queue Length 기반 KEDA 검증은 Redis 공유 Queue와 `queue-worker` Deployment를 대상으로 실행합니다. API Pod가 여러 개여도 동일한 Redis `LLEN`을 조회하므로 Prometheus Query는 `max(sample_queue_length)`를 사용합니다.

## 8. KEDA 검증 시나리오

### 사전 조건

- KEDA 담당자가 `sample_queue_length`를 조회하는 Trigger 또는 ScaledObject를 준비합니다.
- Prometheus 담당자가 `/metrics`를 수집하고 쿼리로 값을 확인합니다.
- 최소/최대 replica와 Queue Length 임계값을 팀에서 합의합니다.

### Scale-Out 확인

1. Queue Length와 현재 replica 수가 안정된 상태인지 확인합니다.
2. `queue-scale-out.js`를 실행합니다.
3. `/api/queue/status`와 Prometheus에서 Queue Length 증가를 확인합니다.
4. KEDA의 polling interval 이후 replica 수가 증가하는지 확인합니다.

```bash
k6 run -e BASE_URL=http://<ingress-url> -e QUEUE_RATE=20 k6/queue-scale-out.js
```

### Scale-In 확인

1. Scale-Out 후 Queue Length가 쌓인 상태를 확인합니다.
2. 생성 부하를 중단하고 `queue-scale-in.js`를 실행합니다.
3. Queue Length가 0 방향으로 감소하는지 확인합니다.
4. KEDA cooldown period 이후 replica 수가 감소하는지 확인합니다.

```bash
k6 run -e BASE_URL=http://<ingress-url> k6/queue-scale-in.js
```

### 연속 패턴 확인

먼저 `queue-scale-out.js`로 생성 부하를 주고, 실행 종료 후 `queue-scale-in.js`로 Worker가 Queue를 소진하는 구간을 관찰합니다. 두 테스트 결과 파일과 시작·종료 시각을 함께 기록합니다.

## 9. Karpenter 검증 시나리오

Karpenter 담당자는 Pod 증가가 기존 노드 용량을 초과할 때 신규 노드가 생성되는지 확인합니다.

1. KEDA 최대 replica와 workload requests가 노드 증설을 유도할 수 있는지 계산합니다.
2. `karpenter-stress.js`로 높은 Queue 생성률과 KEDA Scale-Out을 유도합니다.
3. Pending Pod 발생 여부와 Karpenter 이벤트를 확인합니다.
4. 신규 노드가 생성되고 Pending Pod가 배치되는 시간을 기록합니다.
5. 부하 종료와 KEDA Scale-In 이후 노드 consolidation 동작을 확인합니다.

CPU 자원 자체의 순간 사용량을 관찰하려면 `spike-app`에 `cpu-load.js`를 함께 사용합니다. 단, Karpenter는 실제 CPU 사용량이 아니라 스케줄링되지 못한 Pod의 requests를 중심으로 동작한다는 점을 구분합니다.

## 10. Chronos-2 검증 시나리오

Chronos-2 담당자는 예측 대상 시계열과 실제 부하 구간을 같은 시간축으로 기록합니다.

1. 최소 10분 이상의 안정 구간을 확보합니다.
2. 실행 시각을 기록하고 대상 workload에 적합한 k6 테스트를 수행합니다.
3. CPU, 메모리, replica 수, Queue Length와 요청량을 수집합니다.
4. 예측 결과와 실제 급증 시작점, 최고점, 회복 시점을 비교합니다.
5. 반복 실행 시 동일한 k6 스크립트와 `BASE_URL`, 실행 시간을 기록합니다.

추천 입력 패턴:

- 정상 기준선: `normal-load.js`
- CPU 급증: `cpu-load.js`
- 장시간 반복 패턴: `soak.js`
- Queue 증가/감소: `queue-scale-out.js`, `queue-scale-in.js`

## 11. 결과 공유 항목

테스트 결과를 공유할 때 다음 내용을 포함합니다.

- 대상 환경과 `BASE_URL`
- 대상 workload와 이미지 태그
- 실행한 k6 파일 및 시작/종료 시각
- k6의 `checks`, `http_req_failed`, `http_req_duration`
- CPU, 메모리, replica, node 수 변화
- `sample_queue_length` 변화
- KEDA/Karpenter 이벤트와 오류 로그
