#!/usr/bin/env bash
set -euo pipefail

GATEWAY_NAMESPACE="${GATEWAY_NAMESPACE:-default}"
GATEWAY_NAME="${GATEWAY_NAME:-my-gateway}"
PROMETHEUS_NAMESPACE="${PROMETHEUS_NAMESPACE:-prometheus}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-600s}"

print_diagnostics() {
  kubectl get gateway "${GATEWAY_NAME}" -n "${GATEWAY_NAMESPACE}" -o wide || true
  kubectl describe gateway "${GATEWAY_NAME}" -n "${GATEWAY_NAMESPACE}" || true
  kubectl get httproute -A -o wide || true
  kubectl get pods -n "${PROMETHEUS_NAMESPACE}" -o wide || true
}

wait_for_resource() {
  local resource="$1"
  local namespace="$2"
  local attempts=60

  until kubectl get "${resource}" -n "${namespace}" >/dev/null 2>&1; do
    attempts=$((attempts - 1))
    if [ "${attempts}" -eq 0 ]; then
      echo "Timed out waiting for ${namespace}/${resource} to be created." >&2
      return 1
    fi
    sleep 5
  done
}

trap 'print_diagnostics' ERR

wait_for_resource "gateway/${GATEWAY_NAME}" "${GATEWAY_NAMESPACE}"
kubectl wait \
  --for=condition=Accepted=True \
  "gateway/${GATEWAY_NAME}" \
  -n "${GATEWAY_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Programmed=True \
  "gateway/${GATEWAY_NAME}" \
  -n "${GATEWAY_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

wait_for_resource "deployment/prometheus-stack-grafana" "${PROMETHEUS_NAMESPACE}"
kubectl wait \
  --for=condition=Available=True \
  deployment/prometheus-stack-grafana \
  -n "${PROMETHEUS_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

wait_for_resource \
  "statefulset/prometheus-prometheus-stack-kube-prom-prometheus" \
  "${PROMETHEUS_NAMESPACE}"
kubectl rollout status \
  statefulset/prometheus-prometheus-stack-kube-prom-prometheus \
  -n "${PROMETHEUS_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

trap - ERR
kubectl get gateway "${GATEWAY_NAME}" -n "${GATEWAY_NAMESPACE}" -o wide
kubectl get httproute -A -o wide
kubectl get pods -n "${PROMETHEUS_NAMESPACE}" -o wide
