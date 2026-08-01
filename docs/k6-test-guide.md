# Redis Queue 및 워크로드 k6 테스트

## 공통 실행 방식

모든 신규 시나리오는 `BASE_URL` 환경변수를 사용하며 HTTP 실패율, p95 응답 시간, Check 성공률 Threshold를 포함합니다. Threshold를 만족하지 못하면 k6가 0이 아닌 종료 코드를 반환합니다.

```powershell
k6 run -e BASE_URL=http://localhost:8000 k6/smoke.js
k6 run -e BASE_URL=http://localhost:8000 k6/normal-load.js
```

## Queue Scale-out

Worker 처리 속도보다 빠르게 작업을 등록해야 Queue Length가 증가합니다.

```powershell
k6 run `
  -e BASE_URL=http://localhost:8000 `
  -e QUEUE_RATE=20 `
  -e TEST_DURATION=2m `
  --out json=k6/results/queue-scale-out.json `
  k6/queue-scale-out.js
```

## Queue Scale-in

생성 부하를 중단하고 Worker가 Queue를 비우는 동안 실행합니다. 테스트 종료 시 마지막 Queue Length가 0이 아니면 실패합니다.

```powershell
k6 run `
  -e BASE_URL=http://localhost:8000 `
  -e TEST_DURATION=2m `
  --out json=k6/results/queue-scale-in.json `
  k6/queue-scale-in.js
```

## Soak 및 Karpenter용 부하

```powershell
k6 run -e TEST_DURATION=30m -e VUS=10 k6/soak.js
k6 run -e QUEUE_RATE=100 -e TEST_DURATION=5m k6/karpenter-stress.js
```

`karpenter-stress.js`는 실제 Karpenter가 설치된 EKS에서 Pending Pod와 Node 확장을 유도하기 위한 입력 부하입니다. 로컬 환경에서는 Queue 생성 동작만 검증합니다.
