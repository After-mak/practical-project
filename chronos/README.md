# Chronos-2 선제 오토스케일링 서비스

Thanos/Prometheus에 저장된 `sample-worker` 전체 CPU 시계열을
`amazon/chronos-2` 모델로
예측하고, 기존 FinOps API와 KEDA용 Prometheus 메트릭을 함께 제공합니다.

## API

| Endpoint | 역할 |
|---|---|
| `GET /health/live` | 프로세스 생존 확인 |
| `GET /health/ready` | 최신 예측이 유효한지 확인 |
| `GET /predict/{namespace}/{deployment}` | FinOps Analyzer용 예측 응답 |
| `GET /metrics` | Prometheus·KEDA용 메트릭 |

기본 예측 대상은 `sample-fastapi/sample-worker`이고, Deployment 전체 CPU를
다음 PromQL 형태로 집계합니다.

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

## 실행 모드

| `CHRONOS_MODE` | 동작 |
|---|---|
| `disabled` | 예측을 실행하지 않고 KEDA 신호를 0으로 유지 |
| `shadow` | 예측·API·관측 메트릭만 제공하고 KEDA 신호는 0 |
| `active` | 유효한 예측 Replica를 `chronos_scaling_replicas`로 제공 |

예측이 실패하거나 TTL을 넘으면 `chronos_forecast_valid=0`,
`chronos_scaling_replicas=0`으로 변경됩니다. Sample Worker의 최소 1개 Replica와
실제 Queue 기반 확장은 KEDA ScaledObject가 별도로 보장합니다.

## 주요 메트릭

```text
chronos_predicted_cpu_cores
chronos_predicted_replicas
chronos_scaling_replicas
chronos_forecast_timestamp_seconds
chronos_forecast_start_time_seconds
chronos_forecast_end_time_seconds
chronos_forecast_valid
chronos_forecast_execution_seconds
chronos_forecast_errors_total
chronos_mode
chronos_model_info
```

모든 워크로드 메트릭에는 `namespace`, `deployment` Label이 붙습니다.

## 환경변수

| 변수 | 기본값 |
|---|---|
| `PROM_URL` | `http://thanos-query.prometheus.svc.cluster.local:9090` |
| `CHRONOS_TARGET_DEPLOYMENT` | `sample-worker` |
| `CHRONOS_TARGET_NAMESPACE` | `sample-fastapi` |
| `CHRONOS_POD_PATTERN` | `sample-worker-.*` |
| `CHRONOS_CONTAINER` | `worker` |
| `CHRONOS_MODE` | `shadow` |
| `CHRONOS_THRESHOLD` | `0.3` Core |
| `CHRONOS_CAPACITY_PER_REPLICA` | `0.5` Core |
| `CHRONOS_LOOKBACK_HOURS` | `2` |
| `CHRONOS_PREDICTION_LENGTH` | `12` |
| `CHRONOS_STEP_SECONDS` | `60` |
| `CHRONOS_MIN_REPLICAS` | `1` |
| `CHRONOS_MAX_REPLICAS` | `3` |
| `CHRONOS_FORECAST_INTERVAL_SECONDS` | `60` |
| `CHRONOS_FORECAST_TTL_SECONDS` | `120` |
| `CHRONOS_MODEL_ID` | `amazon/chronos-2` |
| `CHRONOS_FAKE_REPLICAS` | 미설정 |

`CHRONOS_FAKE_REPLICAS=3`을 지정하면 Thanos와 모델을 호출하지 않고 Replica 3
예측을 생성합니다. Fake Metric→KEDA 계약 테스트에서만 사용하고 실제 Shadow·Active
검증에서는 제거합니다.

## 로컬 실행

```bash
python3 -m venv chronos-env
source chronos-env/bin/activate
pip install -r chronos/requirements.txt

export PROM_URL=http://localhost:9090
export CHRONOS_MODE=shadow
uvicorn app:app --app-dir chronos --host 0.0.0.0 --port 8000
```

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/predict/sample-fastapi/sample-worker
curl http://localhost:8000/metrics
```

## 테스트

모델을 다운로드하지 않고 Fake Model·Fake Prometheus 응답으로 핵심 계약을 검증합니다.

```bash
python -m pytest chronos/tests -q
```

검증 범위:

- Deployment 전체 CPU PromQL
- CPU 예측값의 Replica 변환과 최대값 제한
- `disabled`, `shadow`, `active`
- 기존 FinOps `/predict` 응답 계약
- KEDA 메트릭
- 예측 TTL 만료
- Thanos 오류 시 안전한 신호 비활성화

## 컨테이너

```bash
docker build -f chronos/Dockerfile -t chronos-model:local .
docker run --rm -p 8000:8000 \
  -e CHRONOS_MODE=disabled \
  chronos-model:local
```

Kubernetes에서는 GitOps 저장소의 `charts/chronos`가
`monitoring/chronos-model:8000`으로 배포합니다. 기존 `run_pipeline.sh`는 연습
서버 수동 실행 호환용이며, EKS에서는 상시 Deployment를 사용합니다.

## 기존 로컬 파이프라인 호환성

`run_pipeline.sh`가 직접 실행하는 `chronos_prometheus.py` CLI 경로는 기존 기본값을
유지합니다.

- Prometheus: `http://localhost:9090`
- 대상: `default/test-overprovisioned`
- 결과 파일: `~/k8s-manifest/forecast_result.json`
- `kubectl`로 현재 replica 조회
- 임계값 이하면 현재 replica 유지
- 기존 결과 필드 `pod`, `predicted_cpu_usage`, `scale_out_needed`,
  `current_replicas`, `predicted_replicas` 유지

새 Kubernetes API 서비스만 Thanos와 `sample-fastapi/sample-worker`를 기본 대상으로
사용합니다. 두 실행 경로는 동일한 예측 엔진을 공유하지만 기본 설정은 서로 분리되어
있습니다.
