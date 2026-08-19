#!/usr/bin/env bash

# Chronos-2 -> KEDA -> Karpenter 녹화 전 읽기 전용 점검 스크립트.
# 클러스터 리소스를 변경하지 않으며 조회 결과만 출력합니다.
set -u
set -o pipefail

CONTEXT="${CONTEXT:-project03-eks}"
WORKLOAD_NAMESPACE="${WORKLOAD_NAMESPACE:-sample-fastapi}"
CHRONOS_NAMESPACE="${CHRONOS_NAMESPACE:-monitoring}"
KARPENTER_NAMESPACE="${KARPENTER_NAMESPACE:-kube-system}"

WORKER_DEPLOYMENT="${WORKER_DEPLOYMENT:-sample-worker}"
WORKER_SELECTOR="${WORKER_SELECTOR:-app.kubernetes.io/name=sample-fastapi,app.kubernetes.io/component=worker}"
CHRONOS_DEPLOYMENT="${CHRONOS_DEPLOYMENT:-chronos-model}"
CHRONOS_SERVICE="${CHRONOS_SERVICE:-chronos-model}"
CHRONOS_SERVICE_PORT="${CHRONOS_SERVICE_PORT:-8000}"
CHRONOS_SCALEDOBJECT="${CHRONOS_SCALEDOBJECT:-sample-worker}"
NODEPOOL_NAME="${NODEPOOL_NAME:-worker-nodepool}"
EC2NODECLASS_NAME="${EC2NODECLASS_NAME:-worker-nodepool}"

PREDICTED_METRIC="${PREDICTED_METRIC:-chronos_scaling_replicas}"
EXPECTED_MODEL="${EXPECTED_MODEL:-amazon/chronos-2}"
EXPECTED_INITIAL_REPLICAS="${EXPECTED_INITIAL_REPLICAS:-1}"
EXPECTED_REPLICAS="${EXPECTED_REPLICAS:-3}"
EXPECTED_ADDITIONAL_NODES="${EXPECTED_ADDITIONAL_NODES:-}"
REQUIRE_ACTIVE="${REQUIRE_ACTIVE:-true}"

PASS=0
WARN=0
FAIL=0

print_title() {
  printf '\n============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

pass() {
  printf '[PASS] %s\n' "$1"
  PASS=$((PASS + 1))
}

warn() {
  printf '[WARN] %s\n' "$1"
  WARN=$((WARN + 1))
}

fail() {
  printf '[FAIL] %s\n' "$1"
  FAIL=$((FAIL + 1))
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

resource_exists() {
  local resource="$1"
  local name="$2"
  local namespace="${3:-}"

  if [[ -n "${namespace}" ]]; then
    kubectl get "${resource}" "${name}" -n "${namespace}" >/dev/null 2>&1
  else
    kubectl get "${resource}" "${name}" >/dev/null 2>&1
  fi
}

condition_status() {
  local resource="$1"
  local name="$2"
  local condition="$3"
  local namespace="${4:-}"

  if [[ -n "${namespace}" ]]; then
    kubectl get "${resource}" "${name}" -n "${namespace}" \
      -o "jsonpath={.status.conditions[?(@.type==\"${condition}\")].status}" \
      2>/dev/null || true
  else
    kubectl get "${resource}" "${name}" \
      -o "jsonpath={.status.conditions[?(@.type==\"${condition}\")].status}" \
      2>/dev/null || true
  fi
}

print_title "Chronos-2 Recording Pre-check"

echo "실행 시각: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "예상 Context: ${CONTEXT}"
echo "Worker Namespace: ${WORKLOAD_NAMESPACE}"
echo "Chronos Namespace: ${CHRONOS_NAMESPACE}"
echo "예상 모델: ${EXPECTED_MODEL}"

print_title "1. Required Commands"

if command_exists kubectl; then
  pass "kubectl 명령어를 사용할 수 있습니다."
else
  fail "kubectl이 설치되어 있지 않거나 PATH에 없습니다."
  echo
  echo "PASS: ${PASS}"
  echo "WARN: ${WARN}"
  echo "FAIL: ${FAIL}"
  exit 1
fi

if command_exists curl; then
  pass "curl 명령어를 사용할 수 있습니다."
else
  warn "curl이 없습니다. 수동 포트포워딩 후 메트릭 조회가 제한될 수 있습니다."
fi

print_title "2. Kubernetes Context and Connection"

CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

if [[ -z "${CURRENT_CONTEXT}" ]]; then
  fail "현재 Kubernetes Context가 설정되어 있지 않습니다."
  echo "생성 예시: aws eks update-kubeconfig --region ap-northeast-2 --name project03-eks --alias ${CONTEXT}"
elif [[ "${CURRENT_CONTEXT}" == "${CONTEXT}" || "${CURRENT_CONTEXT}" == */"${CONTEXT}" ]]; then
  pass "현재 Context가 대상 클러스터와 일치합니다: ${CURRENT_CONTEXT}"
else
  fail "현재 Context는 ${CURRENT_CONTEXT}이며 예상값은 ${CONTEXT}입니다."
  echo "변경 명령어: kubectl config use-context ${CONTEXT}"
fi

if kubectl cluster-info >/dev/null 2>&1; then
  pass "Kubernetes API Server에 연결할 수 있습니다."
else
  fail "Kubernetes API Server에 연결할 수 없습니다."
fi

print_title "3. Namespaces"

for namespace in "${WORKLOAD_NAMESPACE}" "${CHRONOS_NAMESPACE}" prometheus; do
  if kubectl get namespace "${namespace}" >/dev/null 2>&1; then
    pass "Namespace ${namespace}가 존재합니다."
  else
    fail "Namespace ${namespace}를 찾을 수 없습니다."
  fi
done

print_title "4. Chronos-2 Deployment and Service"

if resource_exists deployment "${CHRONOS_DEPLOYMENT}" "${CHRONOS_NAMESPACE}"; then
  pass "Chronos Deployment ${CHRONOS_NAMESPACE}/${CHRONOS_DEPLOYMENT}가 존재합니다."

  CHRONOS_AVAILABLE="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"

  if [[ "${CHRONOS_AVAILABLE:-0}" -ge 1 ]]; then
    pass "Chronos Deployment가 Available 상태입니다."
  else
    fail "Chronos Deployment의 Available Replica가 없습니다."
  fi

  CHRONOS_MODE="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="chronos")].env[?(@.name=="CHRONOS_MODE")].value}' \
    2>/dev/null || true)"
  CHRONOS_MODEL="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="chronos")].env[?(@.name=="CHRONOS_MODEL_ID")].value}' \
    2>/dev/null || true)"
  LOOKBACK_HOURS="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="chronos")].env[?(@.name=="CHRONOS_LOOKBACK_HOURS")].value}' \
    2>/dev/null || true)"
  PREDICTION_LENGTH="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="chronos")].env[?(@.name=="CHRONOS_PREDICTION_LENGTH")].value}' \
    2>/dev/null || true)"
  STEP_SECONDS="$(kubectl get deployment "${CHRONOS_DEPLOYMENT}" \
    -n "${CHRONOS_NAMESPACE}" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="chronos")].env[?(@.name=="CHRONOS_STEP_SECONDS")].value}' \
    2>/dev/null || true)"

  echo "Mode: ${CHRONOS_MODE:-Unknown}"
  echo "Model: ${CHRONOS_MODEL:-Unknown}"
  echo "Lookback: ${LOOKBACK_HOURS:-Unknown}h"
  echo "Prediction Length: ${PREDICTION_LENGTH:-Unknown}"
  echo "Step: ${STEP_SECONDS:-Unknown}s"

  if [[ "${CHRONOS_MODEL}" == "${EXPECTED_MODEL}" ]]; then
    pass "Chronos 모델이 ${EXPECTED_MODEL}입니다."
  else
    fail "Chronos 모델이 ${CHRONOS_MODEL:-Unknown}입니다. 예상값은 ${EXPECTED_MODEL}입니다."
  fi

  if [[ "${REQUIRE_ACTIVE}" == "true" ]]; then
    if [[ "${CHRONOS_MODE}" == "active" ]]; then
      pass "Chronos가 active 모드입니다."
    else
      fail "Chronos가 ${CHRONOS_MODE:-Unknown} 모드입니다. 녹화 전 active로 변경해야 합니다."
    fi
  elif [[ "${CHRONOS_MODE}" == "active" ]]; then
    pass "Chronos가 active 모드입니다."
  else
    warn "Chronos가 ${CHRONOS_MODE:-Unknown} 모드입니다."
  fi

  kubectl get deployment "${CHRONOS_DEPLOYMENT}" -n "${CHRONOS_NAMESPACE}" -o wide
else
  fail "Chronos Deployment ${CHRONOS_NAMESPACE}/${CHRONOS_DEPLOYMENT}를 찾을 수 없습니다."
fi

if resource_exists service "${CHRONOS_SERVICE}" "${CHRONOS_NAMESPACE}"; then
  pass "Chronos Service ${CHRONOS_NAMESPACE}/${CHRONOS_SERVICE}가 존재합니다."
  kubectl get service "${CHRONOS_SERVICE}" -n "${CHRONOS_NAMESPACE}" -o wide
else
  fail "Chronos Service ${CHRONOS_NAMESPACE}/${CHRONOS_SERVICE}를 찾을 수 없습니다."
fi

echo
echo "Chronos Pods:"
kubectl get pods -n "${CHRONOS_NAMESPACE}" \
  -l app.kubernetes.io/name=chronos-model -o wide 2>/dev/null || true

print_title "5. Chronos Prediction Metrics"

METRICS_PATH="/api/v1/namespaces/${CHRONOS_NAMESPACE}/services/http:${CHRONOS_SERVICE}:${CHRONOS_SERVICE_PORT}/proxy/metrics"
METRICS_OUTPUT="$(kubectl get --raw "${METRICS_PATH}" 2>/dev/null || true)"

if [[ -n "${METRICS_OUTPUT}" ]]; then
  pass "Kubernetes Service Proxy를 통해 Chronos /metrics를 조회했습니다."

  for metric in \
    chronos_model_info \
    chronos_predicted_cpu_cores \
    chronos_predicted_replicas \
    chronos_scaling_replicas \
    chronos_forecast_valid \
    chronos_forecast_timestamp_seconds; do
    if grep -q "^${metric}" <<<"${METRICS_OUTPUT}"; then
      pass "메트릭 ${metric}을 확인했습니다."
      grep "^${metric}" <<<"${METRICS_OUTPUT}" | head -n 3
    else
      fail "메트릭 ${metric}을 찾지 못했습니다."
    fi
  done

  MODEL_INFO_LINE="$(grep '^chronos_model_info{' <<<"${METRICS_OUTPUT}" | head -n 1 || true)"
  FORECAST_VALID_VALUE="$(grep '^chronos_forecast_valid{' <<<"${METRICS_OUTPUT}" \
    | awk 'NR == 1 {print $NF}' || true)"

  if grep -q "model_id=\"${EXPECTED_MODEL}\"" <<<"${MODEL_INFO_LINE}"; then
    pass "노출된 모델 메트릭도 ${EXPECTED_MODEL}을 가리킵니다."
  else
    fail "chronos_model_info에서 ${EXPECTED_MODEL}을 확인하지 못했습니다."
  fi

  if [[ "${FORECAST_VALID_VALUE}" == "1" || "${FORECAST_VALID_VALUE}" == "1.0" ]]; then
    pass "최신 Chronos 예측이 유효합니다."
  else
    fail "chronos_forecast_valid 값이 ${FORECAST_VALID_VALUE:-Unknown}입니다."
  fi
else
  warn "Service Proxy로 /metrics를 조회하지 못했습니다."
  echo "수동 확인:"
  echo "  kubectl port-forward -n ${CHRONOS_NAMESPACE} service/${CHRONOS_SERVICE} 18000:${CHRONOS_SERVICE_PORT}"
  echo "  curl -s http://127.0.0.1:18000/metrics | grep -E 'chronos_(predicted|scaling|forecast|model)'"
fi

print_title "6. KEDA ScaledObject and HPA"

if resource_exists scaledobject "${CHRONOS_SCALEDOBJECT}" "${WORKLOAD_NAMESPACE}"; then
  pass "ScaledObject ${WORKLOAD_NAMESPACE}/${CHRONOS_SCALEDOBJECT}가 존재합니다."

  SCALEDOBJECT_READY="$(condition_status scaledobject "${CHRONOS_SCALEDOBJECT}" Ready "${WORKLOAD_NAMESPACE}")"
  SCALE_TARGET="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.scaleTargetRef.name}' 2>/dev/null || true)"
  MIN_REPLICAS="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.minReplicaCount}' 2>/dev/null || true)"
  MAX_REPLICAS="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.maxReplicaCount}' 2>/dev/null || true)"
  POLLING_INTERVAL="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.pollingInterval}' 2>/dev/null || true)"
  COOLDOWN_PERIOD="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.cooldownPeriod}' 2>/dev/null || true)"
  TRIGGER_NAMES="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{range .spec.triggers[*]}{.name}{" "}{end}' 2>/dev/null || true)"
  TRIGGER_TYPES="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{range .spec.triggers[*]}{.type}{" "}{end}' 2>/dev/null || true)"
  CHRONOS_QUERY="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.triggers[?(@.name=="chronos")].metadata.query}' 2>/dev/null || true)"
  CHRONOS_THRESHOLD="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.triggers[?(@.name=="chronos")].metadata.threshold}' 2>/dev/null || true)"
  CHRONOS_ACTIVATION_THRESHOLD="$(kubectl get scaledobject "${CHRONOS_SCALEDOBJECT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.triggers[?(@.name=="chronos")].metadata.activationThreshold}' 2>/dev/null || true)"

  echo "Ready: ${SCALEDOBJECT_READY:-Unknown}"
  echo "Scale Target: ${SCALE_TARGET:-Unknown}"
  echo "Min/Max Replica: ${MIN_REPLICAS:-Unknown}/${MAX_REPLICAS:-Unknown}"
  echo "Polling/Cooldown: ${POLLING_INTERVAL:-Unknown}s/${COOLDOWN_PERIOD:-Unknown}s"
  echo "Trigger Names: ${TRIGGER_NAMES:-None}"
  echo "Trigger Types: ${TRIGGER_TYPES:-None}"

  if [[ "${SCALEDOBJECT_READY}" == "True" ]]; then
    pass "ScaledObject Ready 상태가 True입니다."
  else
    fail "ScaledObject Ready 상태가 ${SCALEDOBJECT_READY:-Unknown}입니다."
  fi

  if [[ "${SCALE_TARGET}" == "${WORKER_DEPLOYMENT}" ]]; then
    pass "ScaledObject가 ${WORKER_DEPLOYMENT}를 제어합니다."
  else
    fail "ScaledObject의 scaleTargetRef가 ${SCALE_TARGET:-Unknown}입니다."
  fi

  if grep -qw chronos <<<"${TRIGGER_NAMES}"; then
    pass "Chronos 예측 Trigger가 활성화되어 있습니다."
    echo "Chronos Query: ${CHRONOS_QUERY}"
    echo "Threshold: ${CHRONOS_THRESHOLD:-Unknown}"
    echo "Activation Threshold: ${CHRONOS_ACTIVATION_THRESHOLD:-Unknown}"

    if grep -q "${PREDICTED_METRIC}" <<<"${CHRONOS_QUERY}"; then
      pass "KEDA Query가 ${PREDICTED_METRIC}을 조회합니다."
    else
      fail "KEDA Query에서 ${PREDICTED_METRIC}을 찾지 못했습니다."
    fi
  else
    fail "Chronos Trigger가 없습니다. sample-worker를 predictive 모드로 변경해야 합니다."
  fi
else
  fail "ScaledObject ${WORKLOAD_NAMESPACE}/${CHRONOS_SCALEDOBJECT}를 찾을 수 없습니다."
fi

echo
kubectl get scaledobject,hpa -n "${WORKLOAD_NAMESPACE}" 2>/dev/null || true

TARGET_HPA_COUNT=0
while IFS= read -r hpa_name; do
  [[ -z "${hpa_name}" ]] && continue
  hpa_target="$(kubectl get hpa "${hpa_name}" -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.scaleTargetRef.name}' 2>/dev/null || true)"
  if [[ "${hpa_target}" == "${WORKER_DEPLOYMENT}" ]]; then
    TARGET_HPA_COUNT=$((TARGET_HPA_COUNT + 1))
  fi
done < <(kubectl get hpa -n "${WORKLOAD_NAMESPACE}" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)

if [[ "${TARGET_HPA_COUNT}" -eq 1 ]]; then
  pass "${WORKER_DEPLOYMENT}를 제어하는 HPA가 정확히 1개입니다."
elif [[ "${TARGET_HPA_COUNT}" -eq 0 ]]; then
  fail "${WORKER_DEPLOYMENT}를 제어하는 HPA가 없습니다."
else
  fail "${WORKER_DEPLOYMENT}를 제어하는 HPA가 ${TARGET_HPA_COUNT}개입니다. 충돌 여부를 확인해야 합니다."
fi

print_title "7. Worker Deployment and Pods"

if resource_exists deployment "${WORKER_DEPLOYMENT}" "${WORKLOAD_NAMESPACE}"; then
  pass "Worker Deployment ${WORKLOAD_NAMESPACE}/${WORKER_DEPLOYMENT}가 존재합니다."

  DESIRED_REPLICAS="$(kubectl get deployment "${WORKER_DEPLOYMENT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
  AVAILABLE_REPLICAS="$(kubectl get deployment "${WORKER_DEPLOYMENT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)"
  WORKER_REQUESTS="$(kubectl get deployment "${WORKER_DEPLOYMENT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{" CPU="}{.resources.requests.cpu}{" MEMORY="}{.resources.requests.memory}{"\n"}{end}' \
    2>/dev/null || true)"
  WORKER_LABELS="$(kubectl get deployment "${WORKER_DEPLOYMENT}" \
    -n "${WORKLOAD_NAMESPACE}" \
    -o jsonpath='{.spec.selector.matchLabels}' 2>/dev/null || true)"

  echo "Desired Replicas: ${DESIRED_REPLICAS:-0}"
  echo "Available Replicas: ${AVAILABLE_REPLICAS:-0}"
  echo "Resource Requests:"
  echo "${WORKER_REQUESTS:-Unknown}"
  echo "Selector Labels: ${WORKER_LABELS:-Unknown}"

  if [[ "${DESIRED_REPLICAS:-0}" == "${EXPECTED_INITIAL_REPLICAS}" ]]; then
    pass "Worker 초기 Replica가 ${EXPECTED_INITIAL_REPLICAS}개입니다."
  else
    warn "Worker Replica가 ${DESIRED_REPLICAS:-0}개입니다. 녹화 권장 초기값은 ${EXPECTED_INITIAL_REPLICAS}개입니다."
  fi

  if [[ "${AVAILABLE_REPLICAS:-0}" == "${DESIRED_REPLICAS:-0}" ]]; then
    pass "모든 Worker Replica가 Available 상태입니다."
  else
    warn "Desired와 Available Worker Replica 수가 다릅니다."
  fi
else
  fail "Worker Deployment ${WORKLOAD_NAMESPACE}/${WORKER_DEPLOYMENT}를 찾을 수 없습니다."
fi

echo
kubectl get pods -n "${WORKLOAD_NAMESPACE}" -l "${WORKER_SELECTOR}" -o wide 2>/dev/null || true

PENDING_WORKERS="$(kubectl get pods -n "${WORKLOAD_NAMESPACE}" \
  -l "${WORKER_SELECTOR}" \
  --field-selector=status.phase=Pending \
  --no-headers 2>/dev/null | awk 'NF {count++} END {print count+0}')"

if [[ "${PENDING_WORKERS}" -eq 0 ]]; then
  pass "녹화 시작 전 Pending Worker Pod가 없습니다."
else
  warn "현재 Pending Worker Pod가 ${PENDING_WORKERS}개 있습니다."
fi

print_title "8. Karpenter"

KARPENTER_READY="$(kubectl get pods -n "${KARPENTER_NAMESPACE}" \
  -l app.kubernetes.io/name=karpenter \
  -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' \
  2>/dev/null || true)"

if [[ -n "${KARPENTER_READY}" ]] && ! grep -qv '^true$' <<<"${KARPENTER_READY}"; then
  fail "Ready 상태가 아닌 Karpenter Controller Pod가 있습니다."
elif [[ -n "${KARPENTER_READY}" ]]; then
  pass "Karpenter Controller Pod가 모두 Ready 상태입니다."
else
  fail "Karpenter Controller Pod를 찾지 못했습니다."
fi

kubectl get pods -n "${KARPENTER_NAMESPACE}" \
  -l app.kubernetes.io/name=karpenter -o wide 2>/dev/null || true

if resource_exists nodepool "${NODEPOOL_NAME}" ""; then
  pass "NodePool ${NODEPOOL_NAME}이 존재합니다."
  NODEPOOL_READY="$(condition_status nodepool "${NODEPOOL_NAME}" Ready)"

  if [[ "${NODEPOOL_READY}" == "True" ]]; then
    pass "NodePool Ready 상태가 True입니다."
  else
    fail "NodePool Ready 상태가 ${NODEPOOL_READY:-Unknown}입니다."
  fi

  echo "허용 Instance Type:"
  kubectl get nodepool "${NODEPOOL_NAME}" \
    -o jsonpath='{range .spec.template.spec.requirements[?(@.key=="node.kubernetes.io/instance-type")].values[*]}{.}{" "}{end}' \
    2>/dev/null || true
  echo
  echo "허용 Instance Family/Size:"
  kubectl get nodepool "${NODEPOOL_NAME}" \
    -o jsonpath='{range .spec.template.spec.requirements[*]}{.key}{"="}{.values}{"\n"}{end}' \
    2>/dev/null || true
  echo "Consolidation:"
  kubectl get nodepool "${NODEPOOL_NAME}" \
    -o jsonpath='{.spec.disruption.consolidationPolicy}{" after "}{.spec.disruption.consolidateAfter}{"\n"}' \
    2>/dev/null || true
else
  fail "NodePool ${NODEPOOL_NAME}을 찾을 수 없습니다."
fi

if resource_exists ec2nodeclass "${EC2NODECLASS_NAME}" ""; then
  pass "EC2NodeClass ${EC2NODECLASS_NAME}가 존재합니다."
  NODECLASS_READY="$(condition_status ec2nodeclass "${EC2NODECLASS_NAME}" Ready)"

  if [[ "${NODECLASS_READY}" == "True" ]]; then
    pass "EC2NodeClass Ready 상태가 True입니다."
  else
    fail "EC2NodeClass Ready 상태가 ${NODECLASS_READY:-Unknown}입니다."
  fi
else
  fail "EC2NodeClass ${EC2NODECLASS_NAME}를 찾을 수 없습니다."
fi

print_title "9. Node and Capacity Snapshot"

NODE_COUNT="$(kubectl get nodes --no-headers 2>/dev/null \
  | awk 'NF {count++} END {print count+0}')"
NODECLAIM_COUNT="$(kubectl get nodeclaim --no-headers 2>/dev/null \
  | awk 'NF {count++} END {print count+0}')"

echo "현재 Node 수: ${NODE_COUNT}"
echo "현재 NodeClaim 수: ${NODECLAIM_COUNT}"
echo "예상 Worker Replica 수: ${EXPECTED_REPLICAS}"

if [[ -n "${EXPECTED_ADDITIONAL_NODES}" ]]; then
  echo "예상 추가 Node 수: ${EXPECTED_ADDITIONAL_NODES}"
else
  warn "EXPECTED_ADDITIONAL_NODES가 비어 있습니다. 현재 Node 잔여 용량을 보고 녹화 전 기록하세요."
fi

kubectl get nodes \
  -L karpenter.sh/nodepool,node.kubernetes.io/instance-type 2>/dev/null || true

echo
echo "Node Allocatable:"
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory,PODS:.status.allocatable.pods' \
  2>/dev/null || true

echo
echo "현재 NodeClaim:"
kubectl get nodeclaim -o wide 2>/dev/null || true

print_title "10. Recording Values"

cat <<EOF
Kubernetes Context        : ${CURRENT_CONTEXT:-Not configured}
Worker Namespace          : ${WORKLOAD_NAMESPACE}
Chronos Namespace         : ${CHRONOS_NAMESPACE}
Chronos Deployment        : ${CHRONOS_DEPLOYMENT}
Chronos Service           : ${CHRONOS_SERVICE}:${CHRONOS_SERVICE_PORT}
Chronos Model             : ${CHRONOS_MODEL:-Unknown}
Chronos Mode              : ${CHRONOS_MODE:-Unknown}
KEDA ScaledObject         : ${CHRONOS_SCALEDOBJECT}
Worker Deployment         : ${WORKER_DEPLOYMENT}
Karpenter NodePool        : ${NODEPOOL_NAME}
Karpenter EC2NodeClass    : ${EC2NODECLASS_NAME}
Prediction Metric         : ${PREDICTED_METRIC}
Expected Initial Replicas : ${EXPECTED_INITIAL_REPLICAS}
Expected Replicas         : ${EXPECTED_REPLICAS}
Initial Nodes             : ${NODE_COUNT}
Expected Additional Nodes : ${EXPECTED_ADDITIONAL_NODES:-Record manually}
EOF

print_title "11. Final Summary"

echo "PASS: ${PASS}"
echo "WARN: ${WARN}"
echo "FAIL: ${FAIL}"

if [[ "${FAIL}" -gt 0 ]]; then
  echo
  echo "녹화 전 FAIL 항목을 먼저 해결하세요."
  exit 1
fi

echo
echo "치명적인 실패 항목이 없습니다."
echo "WARN 항목을 확인한 뒤 녹화를 진행하세요."
