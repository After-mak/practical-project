#!/bin/sh
# Prometheus initContainer 전용 entrypoint.
# Prometheus 메인 컨테이너가 뜨기 전에, 그 시점에 실제로 살아있는 파드 이름을 조회해서
# KRR용 더미 이력 데이터를 생성하고 TSDB 블록으로 만들어 공유 볼륨(TSDB_PATH)에 기록합니다.
# terraform apply/destroy를 반복하는 dev 환경에서 파드 이름이 매번 바뀌는 문제를 해결하기 위해,
# "미리 만든 데이터를 보존"하는 대신 "매번 그 순간 기준으로 새로 만드는" 방식을 씁니다.
#
# 필요 권한: 이 파드(Prometheus)의 ServiceAccount가 이미 pods get/list/watch 클러스터 권한을
# 갖고 있어(서비스 디스커버리용) 별도 RBAC 없이 동작합니다.
set -eu

TSDB_PATH="${TSDB_PATH:-/prometheus}"
SEED_DAYS="${SEED_DAYS:-2}"  # Prometheus 로컬 retention(2d)에 맞춤 - 그 이상 만들어봤자 즉시 삭제 대상이라 낭비

SCENARIOS_NS="${SCENARIOS_NS:-sample-fastapi}"

echo "[seed-init] KRR 더미 이력 시딩 시작 (namespace=${SCENARIOS_NS}, days=${SEED_DAYS})"

seed_one() {
  deployment="$1"
  component="$2"
  profile="${3:-krr-rightsizing}"

  pod_name=$(kubectl get pods -n "$SCENARIOS_NS" \
    -l "app.kubernetes.io/name=sample-fastapi,app.kubernetes.io/component=${component}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  if [ -z "$pod_name" ]; then
    echo "[seed-init] '${deployment}' 파드를 아직 못 찾음 (component=${component}) - 스킵"
    return 0
  fi

  echo "[seed-init] ${deployment} -> 실제 파드 '${pod_name}' 기준으로 생성 (profile=${profile})"
  om_file="/tmp/${deployment}.om"
  python3 /opt/krr-seed/generate_krr_dummy_history.py \
    --namespace "$SCENARIOS_NS" --deployment "$deployment" --pod "$pod_name" \
    --days "$SEED_DAYS" --profile "$profile" --output "$om_file"

  promtool tsdb create-blocks-from openmetrics "$om_file" "$TSDB_PATH"
}

seed_one "sample-fastapi" "api"
# sample-worker는 Chronos-2의 예측 대상이기도 하므로, 20분 주기 정상->상승->급증->회복
# 패턴(chronos-periodic-spike)으로 생성합니다. 이 패턴은 계속 반복되므로 Chronos의 짧은
# lookback(기본 2시간) 창이 "지금" 어느 시점이든 항상 급증 구간을 포함하게 되어, KRR용
# 더미 데이터처럼 Prometheus 기동 시점에 한 번만 채워도 그 이후 재생성 없이 계속 유효합니다.
seed_one "sample-worker" "worker" "chronos-periodic-spike"

echo "[seed-init] 완료"
