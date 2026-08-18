# Bank of Anthos 장기 트래픽 KRR 검증 Runbook

이 Runbook은 동일한 offered RPS에서 CPU/Memory **request만** 바꾼 PRE/POST를 비교한다. CPU/Memory limit, 애플리케이션 이미지, autoscaling, NodePool, DB 초기 상태는 고정한다. 장시간 Job 생성, Argo CD sync, 인프라 변경은 담당자 승인 후에만 수행한다.

## 구현 계약

- 트래픽: `k6/bank-of-anthos-long-run.js`
- 실행 리소스: `charts/mak-app/templates/7-loadgen.yaml`
- KRR 식별자: `namespace/workload/container`
- 매핑: `finops/bank-workload-map.json`
- 실행 metadata 예시: `k6/bank-krr-run-metadata.example.json`
- 고정 성공 기준: `k6/bank-krr-success-criteria.json`
- 수집: `k6/collect_bank_krr_run.py`
- 비교: `k6/compare_bank_krr_runs.py`
- 결과에는 Secret, 전체 환경변수 또는 JWT를 저장하지 않는다.
- Queue producer가 Bank 코드에 없으므로 이번 검증은 Queue/Hybrid 결과를 포함하지 않는다.

## 실행 전 차단 조건

다음 중 하나라도 실패하면 Smoke/Pilot/PRE를 시작하지 않는다.

1. EKS API와 DNS가 정상이고 frontend/backend Pod가 Ready다.
2. frontend Rollout이 진행 또는 수동 pause 상태가 아니다.
3. Prometheus에 metric contract의 Kubernetes 지표가 존재한다.
4. Prometheus에 Thanos sidecar가 있고 sidecar upload 오류가 없다.
5. S3 block에 `meta.json`, `index`, `chunks`가 있으며 Store Gateway가 인식한다.
6. Thanos Query에서 2일 이전의 알려진 시계열을 조회할 수 있다.
7. AWS Budget 경고, Karpenter NodePool 상한, HPA/KEDA max replica를 담당자가 확인했다.
8. KRR v1.29.0 소스는 Argo Rollout 조회를 지원한다. 다만 현재 클러스터에서 frontend Rollout 결과가 실제 출력되는지 확인하지 못했으므로, 결과가 없으면 frontend 적용은 blocker다.
9. Load generator에 `dropped_iterations`가 없고 CPU가 limit 근처에 붙지 않는다.

확인 예:

```bash
kubectl get pods -n frontend -o wide
kubectl get rollout mak-app-rollout -n frontend
kubectl get pods,deploy -n backend -o wide
kubectl get hpa,scaledobject -A
kubectl get nodes -L role,node-role,karpenter.sh/nodepool
kubectl get pod -n prometheus -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.name}{" "}{end}{"\n"}{end}'
kubectl logs -n prometheus <prometheus-pod> -c thanos-sidecar --since=24h
```

## Secret와 재현성

전용 테스트 사용자를 사용하고 Secret은 클러스터에 수동 생성한다. 명령 이력에 실제 값을 남기지 않도록 파일 또는 보안 입력 경로를 사용한다.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bank-loadgen-credentials
  namespace: frontend
type: Opaque
stringData:
  username: REDACTED
  password: REDACTED
  recipient-account: REDACTED
```

기본 `paymentPercent=0`은 로그인과 `/home` 조회 중심 흐름이며, 한 요청으로 frontend가 balance, history, contacts backend를 병렬 호출한다. 송금 검증은 충분한 초기 잔액을 가진 PRE/POST 전용 사용자를 동일 snapshot/seed로 복원할 수 있을 때만 별도 시나리오로 활성화한다.

각 실행 전 아래 동등성 metadata를 작성한다. POST에서 다른 것은 GitOps commit과 request 값뿐이어야 한다.

```json
{
  "application_image": "repository@sha256:...",
  "loadgen_image": "grafana/k6@sha256:...",
  "scenario_config": {
    "profile": "smoke",
    "time_scale": "1",
    "cycles": "1",
    "low_rps": "1",
    "normal_rps": "10",
    "peak_rps": "25",
    "spike_rps": "40",
    "recovery_rps": "3",
    "payment_percent": "0"
  },
  "db_state_id": "snapshot-or-seed-id",
  "autoscaling": {
    "frontend_max": 10,
    "backend_max": 5
  },
  "node_pool": {
    "name": "recorded-name",
    "limits": "recorded-limits"
  }
}
```

## 30분 Smoke

프로필은 Low 5분 → Normal 10분 → Peak 5분 → Spike 5분 → Recovery 5분이다.

1. 새 `runId`를 정하고 차트를 로컬 렌더링한다.
2. 승인 후에만 GitOps 반영 및 Argo CD sync를 수행한다.
3. Job 시작 UTC, 앱/GitOps commit, image digest, scenario hash를 기록한다.
4. 로그인 성공, home business validation, offered RPS, p95/p99/error를 확인한다.
5. loadgen CPU, `dropped_iterations`, target Pod/Node 폭주 여부를 확인한다.
6. Job 로그의 마지막 JSON을 `k6-summary.json`으로 보존한다.
7. Prometheus/Thanos 쿼리를 수집하고 결과를 즉시 외부 보존한다.

렌더링 예:

```bash
helm template mak-app ../mak-argocd-deploy/charts/mak-app \
  --namespace frontend \
  --set components.backend=false \
  --set loadgen.enabled=true \
  --set loadgen.runId=boa-smoke-001 \
  --set loadgen.phase=smoke \
  --set loadgen.profile=smoke
```

기본 remote-write는 꺼져 있다. 보안/네트워크 검토 후 Prometheus receiver가 승인된 경우에만 `loadgen.prometheusRemoteWriteEnabled=true`를 쓴다. 그렇지 않으면 Job stdout의 summary JSON을 사용한다.

## Pilot과 본 실험

- 2시간 Pilot: long 프로필 `TIME_SCALE=0.025`, `CYCLES=60` (2분 cycle × 60).
- 6시간 Pilot: long 프로필 `TIME_SCALE=0.075`, `CYCLES=60` (6분 cycle × 60). 실행 전 `k6 inspect`로 종료 시각을 다시 확인한다.
- 권장 본 실험: long profile 80분 cycle × 18 = 24시간.
- 일정 제한 시 최소 6시간을 사용하고 보고서에 한계를 명시한다.
- PRE 종료 직후 JSON/CSV를 먼저 내보내고 즉시 KRR을 실행한다. 현재 통합은 KRR의 `history_duration`만 제어하므로 임의의 과거 절대 시작/종료 시각을 고정하지 못한다. KRR v1.29.0은 종료시각을 실행 시점 `now`로 정하므로 종료 지연만큼 범위가 밀릴 수 있다. `ended_at`, KRR 실행 UTC, duration을 함께 기록하고 지연이 크면 결과를 무효화한다.
- KRR 적용은 `resources.*.requests`만 수정하며 limits를 유지한다.
- 모든 새 revision이 Ready이고 Rollout이 완료된 뒤 15~30분 안정화하고 POST를 시작한다.

KRR 예:

```bash
krr simple --prometheus-url http://thanos-query.prometheus.svc.cluster.local:9090 \
  -n backend --formatter json --cpu_percentile 95 --history_duration 24 --quiet
krr simple --prometheus-url http://thanos-query.prometheus.svc.cluster.local:9090 \
  -n frontend --formatter json --cpu_percentile 95 --history_duration 24 --quiet
```

frontend 결과에 `mak-app-rollout/mak-container`가 없으면 조용히 제외하지 말고 blocker로 기록한다.

## 수집과 비교

```bash
python3 k6/collect_bank_krr_run.py \
  --run-id boa-krr-pre-001 --phase pre \
  --start 2026-08-13T04:00:00Z --end 2026-08-14T04:00:00Z \
  --prometheus-url http://thanos-query.prometheus.svc.cluster.local:9090 \
  --application-commit <sha> --gitops-commit <sha> \
  --scenario boa-long-cycle-v1 --scenario-file k6/bank-of-anthos-long-run.js \
  --krr-executed-at 2026-08-14T04:02:00Z \
  --krr-history-duration 24h --k6-summary k6-summary.json \
  --equivalence-metadata equivalence.json --krr-results krr-pre.json \
  --output results/pre.json --csv-output results/pre.csv

python3 k6/compare_bank_krr_runs.py \
  --pre results/pre.json --post results/post.json \
  --thresholds k6/bank-krr-success-criteria.json \
  --json-output results/comparison.json \
  --markdown-output results/comparison.md \
  --csv-output results/comparison.csv
```

CPU core-hour와 memory GiB-hour 단가를 명시하면 request 기반 할당비용 추정치를 계산한다. 이는 AWS 청구액이 아니다.

## 즉시 중단 기준

- OOMKilled 또는 리소스 부족 restart 발생
- 시스템 오류율 1% 이상
- p95가 PRE 대비 10% 초과 또는 p99가 15% 초과 악화
- 성공 throughput이 PRE의 95% 미만
- 평균 CPU throttling 5% 이상 또는 p95 20% 이상
- loadgen dropped iteration 지속
- Karpenter/HPA가 사전 합의 상한에 도달
- Thanos 데이터 보존 또는 시각 동기화가 깨짐

종료 후 Job, 비정상 Pod, 확장된 Worker Node와 잔존 EC2/ALB/ElastiCache/EBS/Public IPv4를 읽기 전용으로 점검하고, 삭제는 별도 승인 후 수행한다.
