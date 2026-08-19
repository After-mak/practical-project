# KRR 더미 이력 데이터 (시연용)

새로 만든 dev 클러스터는 실사용 이력이 없어서 KRR이 `?`(데이터부족)만 반환합니다.
이 스크립트들은 KRR이 실제로 쓰는 Prometheus 메트릭(`container_cpu_usage_seconds_total`,
`container_memory_working_set_bytes`)을 과거 타임스탬프로 채운 뒤 Prometheus TSDB에
직접 백필해서, 시연 때 KRR이 바로 의미 있는 추천값을 내도록 합니다.

## 준비된 시나리오

| deployment | 스토리 | 현재 request | 실사용 평균(시뮬레이션) |
|---|---|---|---|
| `sample-fastapi` | 과다 프로비저닝 → 큰 폭 절감 데모 | 100m / 128Mi | ~12m CPU, ~42Mi 메모리 |
| `sample-worker` | 이미 잘 맞춰진 케이스 → 소폭 변화 데모 | 100m / 128Mi | ~70m CPU, ~118Mi 메모리 |

## 사용법

```bash
# dev-k8s가 떠있고 kubectl 컨텍스트가 맞춰진 상태에서
./backfill_krr_history.sh sample-fastapi sample-fastapi
./backfill_krr_history.sh sample-fastapi sample-worker
```

내부적으로 하는 일:
1. 실제 떠있는 파드 이름을 `kubectl get pods`로 조회 (재시작마다 이름이 바뀌므로 매번 새로 조회)
2. `generate_krr_dummy_history.py`로 최근 7일치 OpenMetrics 데이터 생성 (Prometheus retention 7d에 맞춤)
3. `promtool tsdb create-blocks-from openmetrics`로 TSDB 블록 생성
4. `kubectl cp`로 Prometheus 파드의 데이터 디렉터리에 블록 복사
5. Prometheus 파드 재시작 (새 블록은 프로세스 시작 시점에만 인식됨)

## 검증한 것 / 못한 것

- `generate_krr_dummy_history.py`가 만든 OpenMetrics 파일은 `promtool tsdb create-blocks-from openmetrics`로
  실제 블록 생성까지 되는 것을 로컬에서 확인했고, 임시 Prometheus를 띄워 KRR과 동일한 PromQL
  (`quantile_over_time(0.95, rate(...)[75s]) [7d:75s]` 등)로 조회해 두 시나리오 모두 현실적인 값이
  나오는 것까지 확인했습니다.
- `backfill_krr_history.sh`의 `kubectl cp`/Prometheus 재시작 부분은 인프라가 destroy된 상태에서
  작성해 **실제 클러스터로는 아직 검증하지 못했습니다.** `PROM_POD`/`PROM_DATA_DIR`은
  kube-prometheus-stack 기본 명명 규칙 기준 추정치이니, dev-k8s가 뜨면 실제 파드 이름/데이터 경로를
  `kubectl -n prometheus get pods`, `kubectl -n prometheus describe pod <pod>`로 확인 후 필요하면 수정하세요.

## 필요 도구

- `promtool` (Prometheus 배포판에 포함, 로컬 PATH에 있어야 함)
- `kubectl` (dev-k8s 클러스터 컨텍스트)
