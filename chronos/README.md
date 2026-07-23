# Chronos-2 CPU 사용량 예측

Prometheus에 쌓인 CPU 사용량 히스토리를 Amazon Chronos-2로 예측해서,
스케일아웃 필요 여부와 권장 replica 수를 `forecast_result.json`으로 출력합니다.
이 결과는 `alarm/generate_report.py`가 읽어서 FinOps 리포트에 반영합니다.

## 설치

```bash
python3 -m venv chronos-env
source chronos-env/bin/activate
pip install -r chronos/requirements.txt
```

## 실행

```bash
source chronos-env/bin/activate
python3 chronos/chronos_prometheus.py
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PROM_URL` | `http://localhost:9090` | Prometheus 주소 |
| `CHRONOS_TARGET_DEPLOYMENT` | `test-overprovisioned` | 예측 대상 Deployment 이름 |
| `CHRONOS_TARGET_NAMESPACE` | `default` | 대상 네임스페이스 |
| `CHRONOS_POD_PATTERN` | `<TARGET_DEPLOYMENT>.*` | Prometheus 쿼리용 파드 이름 정규식 |
| `CHRONOS_THRESHOLD` | `0.3` | 스케일아웃 판단 임계값 |
| `CHRONOS_CAPACITY_PER_REPLICA` | `0.5` | replica 당 CPU 처리 용량(코어) |
| `CHRONOS_LOOKBACK_HOURS` | `2` | 과거 데이터 조회 기간(시간) |
| `FORECAST_FILE` | `~/k8s-manifest/forecast_result.json` | 예측 결과 출력 경로 |

## 출력 (forecast_result.json)

`timestamp`, `pod`, `predicted_cpu_usage`, `scale_out_needed`, `current_replicas`, `predicted_replicas`

## 자동 실행 (cron)

`run_pipeline.sh`가 Prometheus port-forward → 예측 → 리포트 생성까지 한 번에 처리합니다.
현재 연습 서버에는 1시간마다 자동 실행되도록 cron이 등록되어 있습니다.

```bash
crontab -l
# 0 * * * * /home/ubuntu/practical-project/chronos/run_pipeline.sh
```

로그는 `chronos/pipeline.log`에 쌓입니다.

> 참고: 이건 연습 서버 기준 cron 설정입니다. 실제 운영 환경(EKS)에서는
> 이 스크립트 로직을 컨테이너화해서 Kubernetes CronJob으로 배포하는 것을 권장합니다.
