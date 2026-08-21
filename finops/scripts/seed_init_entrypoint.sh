#!/bin/sh
# Prometheus initContainer 전용 entrypoint.
# Prometheus 메인 컨테이너가 뜨기 전에, 그 시점에 실제로 살아있는 파드 이름을 조회해서
# KRR/Chronos용 더미 이력 데이터를 생성하고 TSDB 블록으로 만들어 공유 볼륨(TSDB_PATH)에 기록합니다.
# terraform apply/destroy를 반복하는 dev 환경에서 파드 이름이 매번 바뀌는 문제를 해결하기 위해,
# "미리 만든 데이터를 보존"하는 대신 "매번 그 순간 기준으로 새로 만드는" 방식을 씁니다.
#
# 필요 권한: 이 파드(Prometheus)의 ServiceAccount가 이미 pods get/list/watch 클러스터 권한을
# 갖고 있어(서비스 디스커버리용) 네임스페이스를 가리지 않고 별도 RBAC 없이 동작합니다.
set -eu

TSDB_PATH="${TSDB_PATH:-/prometheus}"
SEED_DAYS="${SEED_DAYS:-2}"  # Prometheus 로컬 retention(2d)에 맞춤 - 그 이상 만들어봤자 즉시 삭제 대상이라 낭비

echo "[seed-init] KRR/Chronos 더미 이력 시딩 시작 (days=${SEED_DAYS})"

seed_one() {
  namespace="$1"
  deployment="$2"
  selector="$3"

  pod_name=$(kubectl get pods -n "$namespace" \
    -l "$selector" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  if [ -z "$pod_name" ]; then
    echo "[seed-init] '${namespace}/${deployment}' 파드를 아직 못 찾음 (selector=${selector}) - 스킵"
    return 0
  fi

  echo "[seed-init] ${namespace}/${deployment} -> 실제 파드 '${pod_name}' 기준으로 생성"
  om_file="/tmp/${namespace}-${deployment}.om"
  python3 /opt/krr-seed/generate_krr_dummy_history.py \
    --namespace "$namespace" --deployment "$deployment" --pod "$pod_name" \
    --days "$SEED_DAYS" --output "$om_file"

  promtool tsdb create-blocks-from openmetrics "$om_file" "$TSDB_PATH"
}

# --- sample-fastapi 네임스페이스 ---
seed_one "sample-fastapi" "sample-fastapi" "app.kubernetes.io/name=sample-fastapi,app.kubernetes.io/component=api"
# sample-worker는 Chronos-2의 예측 대상이기도 하므로, 20분 주기 정상->상승->급증->회복
# 패턴(chronos-periodic-spike)으로 생성합니다. 이 패턴은 계속 반복되므로 Chronos의 짧은
# lookback(기본 2시간) 창이 "지금" 어느 시점이든 항상 급증 구간을 포함하게 되어, KRR용
# 더미 데이터처럼 Prometheus 기동 시점에 한 번만 채워도 그 이후 재생성 없이 계속 유효합니다.
seed_one "sample-fastapi" "sample-worker" "app.kubernetes.io/name=sample-fastapi,app.kubernetes.io/component=worker"

# --- Bank of Anthos 프론트엔드 네임스페이스(frontend) ---
# workload 이름은 Argo Rollout의 실제 metadata.name인 "mak-app-rollout" (finops-apply.yaml의
# 케이스 매핑과 동일하게 맞춤 - "frontend"는 네임스페이스 이름일 뿐 workload 이름이 아닙니다).
seed_one "frontend" "mak-app-rollout" "app=frontend"

# --- Bank of Anthos 백엔드 네임스페이스(backend) ---
# mak-app 차트(templates/2-microservices.yaml)에서 각 서비스 파드는 서비스 본체 컨테이너 +
# redis-queue worker 사이드카 컨테이너를 함께 가지므로, 파드당 한 번만 호출하면
# generate_krr_dummy_history.py가 두 컨테이너 이력을 한 파일에 같이 채워줍니다.
seed_one "backend" "userservice" "app=userservice"
seed_one "backend" "contacts" "app=contacts"
seed_one "backend" "balancereader" "app=balancereader"
seed_one "backend" "ledgerwriter" "app=ledgerwriter"
seed_one "backend" "transactionhistory" "app=transactionhistory"

echo "[seed-init] 완료"
