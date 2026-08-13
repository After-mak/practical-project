# Bank of Anthos KRR Gap Report

기준: 2026-08-13, 두 저장소의 최신 `origin/main` 조사와 로컬 정적 검증 결과.

## 저장소

| 저장소 | 경로 | 기준 브랜치 | 사용자 선행 변경 |
|---|---|---|---|
| 애플리케이션·인프라 | `/home/user1/project/sil-p/practical-project` | `codex/boa-krr-long-traffic` from `origin/main` | 작업 시작 시 없음 |
| GitOps | `/home/user1/project/sil-p/mak-argocd-deploy` | `codex/boa-krr-long-traffic` from `origin/main` | 작업 시작 시 없음 |

commit, push, Argo CD sync, 클러스터 변경, 장시간 테스트는 수행하지 않았다.

## 조사 결과

1. frontend는 `frontend/Rollout/mak-app-rollout/mak-container`, backend는 `backend`의 5개 Deployment이며 각각 앱과 `worker` 컨테이너가 있다.
2. frontend request/limit과 worker request/limit은 기존 값이 있었지만 backend 앱 컨테이너 request가 없었다. 기존 동작을 보존해 앱 request만 명시하고 기존에 없던 limit은 빈 값으로 유지했다.
3. 기존 loadgen은 replicas 0인 Locust Deployment이며 고정 `USERS=800` 방식이었다. 소스·패턴·run metadata·PRE/POST 동등성 장치가 없었다.
4. Prometheus 정적 설정과 차트에서 cAdvisor/kube-state-metrics 계열 metric 사용 경로는 확인했지만, 실클러스터 API DNS 실패로 실제 Bank 시계열 존재 여부는 미확인이다.
5. KRR parser는 workload만으로 결과를 찾을 수 있어 다중 컨테이너가 모호했다. 식별자를 `namespace/workload/container`로 변경했다.
6. KRR v1.29.0 공식 소스에서 Argo Rollout 조회 구현을 확인했다. 다만 RBAC·실제 frontend 결과 출력은 클러스터 API DNS 실패로 미확인이라 적용 전 확인이 필요하다.
7. Terraform에 Prometheus sidecar object storage Secret과 Thanos Query/Store 구성이 있으나 sidecar 로그, S3 block, Store 인식, 2일 이전 query는 API 접근 실패로 미확인이다.
8. KEDA/worker 설정은 존재하지만 Bank 전용 Redis queue producer는 애플리케이션 소스에서 발견되지 않았다. Queue/Hybrid 결과는 1차 실험에서 제외한다.
9. frontend의 `ENABLE_PROMETHEUS` 설정은 보였지만 backend 공통 설정은 `ENABLE_METRICS=false`였다. 1차 결과는 k6 E2E와 컨테이너 리소스/안정성의 두 층으로 구분한다.
10. KRR v1.29.0은 `history_duration` 시간 범위를 지원하지만 종료시각을 실행 시점 `now`로 정한다. 절대 PRE 시작·종료 시각 인자는 없어 PRE 종료 직후 실행하고 KRR 실행 UTC를 기록하는 운영 가드가 필요하다.

## 실환경 Blocker

- EKS API endpoint DNS가 현재 환경에서 해석되지 않아 Pod, 실제 metric, KRR 결과, Rollout 발견을 검증할 수 없다.
- Thanos sidecar/S3/Store/Query 장기 보존 검증 전에는 48시간 이상 실험을 시작하면 안 된다.
- frontend Rollout이 KRR 결과에 없으면 frontend 자동 적용을 중단하고 별도 recommendation 경로를 결정해야 한다.
- Prometheus remote-write receiver는 보안 검토 없이 활성화하지 않았으며 기본값은 off다.
- AWS Budget, Karpenter NodePool 상한, HPA/KEDA 최대 replica는 Smoke 승인 전에 운영자가 확인해야 한다.

## 구현으로 해소한 항목

- arrival-rate 기반 30분 Smoke와 80분 반복/24시간 long 시나리오
- Secret 참조형 유한 Kubernetes Job과 실행별 이름
- 11개 컨테이너 resource values 및 정확한 Workflow 매핑
- 컨테이너별 KRR parser, 명시적 history duration, CPU p95
- Prometheus/Thanos 수집기, PRE/POST 비교기, 고정 성공 기준, JSON/CSV 계약
- Smoke/Pilot/PRE/POST Runbook과 정적·단위·Helm 테스트
