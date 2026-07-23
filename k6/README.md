# Sample FastAPI 워크로드·KRR 관측 테스트

모든 스크립트는 `BASE_URL`로 대상을 선택합니다. 부하·지연·오류·Queue 변경 API는
`LOAD_TEST_TOKEN`과 `X-Test-Token` 헤더가 일치해야 합니다. Token은 명령 기록이나
저장소에 남기지 말고 VMware 셸 환경변수 또는 Secret Manager에서 주입합니다.

## 시나리오

| 시나리오 | 파일 | 기본 부하 | 관측 목적 |
|---|---|---:|---|
| Baseline | `baseline-test.js` | 10 req/s, 10분 | 정상 CPU·Memory·응답시간 기준 |
| Overallocated | `overallocated-test.js` | 2 req/s, 30분 | 높은 Request 대비 실제 사용량 |
| Idle | `idle-test.js` | 30초당 1회, 30분 | 유휴 Replica·최소 사용량 |
| Spike | `spike-test.js` | 1 → 10 → 1 req/s | CPU 급증과 회복 |
| Queue/KEDA | `queue-scale-test.js` | 20 jobs/s, 30초 | Queue 증가·Worker 1→3→1 |

각 전용 Service를 포트포워딩한 다음 실행합니다.

```bash
export LOAD_TEST_TOKEN='Secret에서 읽은 값'
kubectl -n sample-fastapi port-forward service/sample-fastapi-baseline 18001:8000
k6 run -e BASE_URL=http://127.0.0.1:18001 k6/baseline-test.js
```

환경변수로 요청률과 시간을 재현 가능하게 변경할 수 있습니다.

```bash
k6 run \
  -e BASE_URL=http://127.0.0.1:18001 \
  -e REQUEST_RATE=10 \
  -e TEST_DURATION=30m \
  k6/baseline-test.js

k6 run \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e LOAD_TEST_TOKEN="$LOAD_TEST_TOKEN" \
  -e QUEUE_RATE=20 \
  -e LOAD_DURATION=30s \
  -e DRAIN_DURATION=8m \
  k6/queue-scale-test.js
```

## KRR 전달용 관측 기록

`run_observation.py`는 UTC 시작·종료 시간, k6 summary, Deployment·Pod·HPA 전후 상태와
분석에 사용할 PromQL을 `k6/results` JSON으로 남깁니다.

```bash
python3 k6/run_observation.py overallocated \
  --base-url http://127.0.0.1:18002 \
  --env REQUEST_RATE=2 \
  --env TEST_DURATION=30m

python3 k6/run_observation.py queue \
  --base-url http://127.0.0.1:8000 \
  --env LOAD_TEST_TOKEN="$LOAD_TEST_TOKEN" \
  --env QUEUE_RATE=20 \
  --env LOAD_DURATION=30s \
  --env DRAIN_DURATION=8m
```

KRR 담당자에게 다음 항목을 함께 전달합니다.

- observation JSON의 `started_at`과 `ended_at`
- Namespace·Deployment와 `workload-type`
- k6 요청률·실패율·p95
- Deployment requests/limits
- Prometheus CPU·Memory·Queue Length
- 현재/Desired Replica 변화
- KRR CPU·Memory 권장값

`k6/results`는 실행 결과 디렉터리이며 Secret이 포함될 수 있으므로 Git에 커밋하지 않습니다.

## Queue/KEDA 완료 조건

1. `sample_queue_length`가 threshold 5를 초과한다.
2. `keda-hpa-sample-worker` Desired Replica가 증가한다.
3. Worker가 1개에서 최대 3개까지 증가한다.
4. Pending과 Processing Queue가 모두 0이 된다.
5. HPA 안정화 시간 이후 Worker가 1개로 감소한다.
6. `sample_queue_dead_letter_length`가 0이며 작업 유실이 없다.
