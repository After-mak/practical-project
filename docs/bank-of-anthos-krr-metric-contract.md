# Bank of Anthos KRR 검증 Metric Contract

모든 시간은 UTC이며 연속 시계열은 `query_range`를 사용하고, Restart/OOM의 실험 구간 증가는 종료 UTC의 instant query로 정확한 window를 평가한다. 최종 통계는 `kubectl top` 또는 화면 캡처로 계산하지 않는다.

## 실행 식별자

- `run_id`: 실행마다 유일
- `phase`: `smoke|pilot|pre|post`
- `scenario`: 시나리오 이름
- `flow`: `login|overview|overview_retry|payment|bank_flow`
- 대상 리소스: `namespace/workload/container`

## End-to-End k6

| Metric | 의미 |
|---|---|
| `boa_offered_flows` | 예약된 사용자 flow 수 |
| `boa_offered_requests` | 실제 발행 HTTP 요청 수 |
| `boa_successful_requests` | 2xx/3xx 요청 수 |
| `boa_system_failures` | status 0, timeout 또는 5xx |
| `boa_business_failures` | 로그인/화면 내용 등 business validation 실패 |
| `boa_intentional_4xx` | 상태 변경 flow의 분리된 4xx |
| `boa_flow_success` | 전체 flow 성공 Rate |
| `boa_e2e_latency_ms` | overview 및 전체 flow Trend(p50/p95/p99/avg/max) |

기본 증거는 Job stdout과 `/results/summary.json`이다. Prometheus remote-write는 receiver와 네트워크 정책이 승인된 환경에서만 opt-in한다.

## Kubernetes / Prometheus

필수 metric:

- `container_cpu_usage_seconds_total`
- `container_memory_working_set_bytes`
- `container_cpu_cfs_throttled_periods_total`
- `container_cpu_cfs_periods_total`
- `kube_pod_container_resource_requests`
- `kube_pod_container_resource_limits`
- `kube_pod_container_status_restarts_total`
- `kube_pod_container_status_last_terminated_reason`
- `kube_pod_info`
- `kube_node_labels`

컨테이너별 selector는 namespace, workload prefix pod regex와 exact container label을 함께 쓴다. 앱과 worker를 합산하지 않는다.

- CPU usage: `sum(rate(container_cpu_usage_seconds_total[5m]))`
- Memory working set: `sum(container_memory_working_set_bytes)`
- CPU usage/request: usage ÷ `kube_pod_container_resource_requests{resource="cpu"}`
- Memory usage/request: working set ÷ request bytes
- Throttling: throttled periods rate ÷ periods rate
- Restart: 종료 UTC instant query에서 실험 구간 increase
- OOM: 종료 UTC instant query에서 실험 구간의 last terminated reason
- Pod count: `count(kube_pod_info)`

각 시계열은 avg, p95, max를 저장한다. 값이 없으면 0으로 추측하지 않고 null 또는 collection warning을 기록한다.

## Node와 비용 담당자 전달

수집 결과 JSON/CSV에 컨테이너 request, usage, replicas, 안정성 지표를 포함한다. 별도 Node 비용 담당자는 다음을 동일 UTC 범위로 보강한다.

- 평균/최대 Karpenter Worker Node 수
- Node별 instance type, capacity type, 시작/종료 시각
- 실제 node-hour 단가
- 고정 node와 탄력 node 구분

비교기의 비용은 단가가 입력된 경우에만 계산하며 `estimated_allocation_cost`로 표시한다. AWS 청구액으로 표기하지 않는다.

## 결과 스키마
정식 JSON Schema는 `k6/schema/bank-krr-run.schema.json`과 `k6/schema/bank-krr-comparison.schema.json`이며, CSV column은 각 수집기·비교기의 header와 동일하다. 성공 기준은 `k6/bank-krr-success-criteria.json`에서 실행 전에 고정한다.


`collect_bank_krr_run.py` 결과:

- 실행 metadata와 scenario SHA-256
- PRE/POST 동등성 metadata
- k6 HTTP 집계
- `workloads[namespace/workload/container]`
- 원본 KRR recommendation JSON
- 수집 실패 대상과 오류 문자열

`compare_bank_krr_runs.py` 결과:

- 동등성 mismatch 목록
- 전역 PASS/FAIL checks
- p95/p99와 throughput 변화
- CPU/Memory request capacity 절감
- 컨테이너별 throttle/OOM/restart 판정
- 선택적 request 기반 비용 추정
