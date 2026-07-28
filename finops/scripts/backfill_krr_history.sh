#!/bin/bash
# KRR 더미 이력 데이터를 실제 dev 클러스터의 Prometheus TSDB에 백필합니다.
# generate_krr_dummy_history.py로 만든 OpenMetrics 데이터를
# `promtool tsdb create-blocks-from openmetrics`로 블록화한 뒤,
# 실행 중인 Prometheus 파드에 복사하고 재시작해 인식시킵니다.
#
# 사용법: ./backfill_krr_history.sh <namespace> <deployment> [days]
# 예:    ./backfill_krr_history.sh sample-fastapi sample-fastapi
#        ./backfill_krr_history.sh sample-fastapi sample-worker
#
# 주의: PROM_POD/PROM_DATA_DIR은 kube-prometheus-stack 기본 명명 규칙 기준
# 추정치입니다(인프라가 destroy된 상태에서 작성해 실클러스터로 검증 못함).
# 실제 파드 이름이 다르면 `kubectl -n prometheus get pods`로 확인 후 수정하세요.

set -euo pipefail

NAMESPACE="${1:?namespace를 입력하세요 (예: sample-fastapi)}"
DEPLOYMENT="${2:?deployment 이름을 입력하세요 (sample-fastapi 또는 sample-worker)}"
DAYS="${3:-7}"

PROM_NAMESPACE="prometheus"
PROM_POD="prometheus-prometheus-stack-kube-prom-prometheus-0"
PROM_CONTAINER="prometheus"
PROM_DATA_DIR="/prometheus"

if [ "$DEPLOYMENT" = "sample-worker" ]; then
  COMPONENT="worker"
else
  COMPONENT="api"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "[backfill] 실제 파드 이름 조회 중..."
POD_NAME=$(kubectl -n "$NAMESPACE" get pods \
  -l "app.kubernetes.io/name=sample-fastapi,app.kubernetes.io/component=$COMPONENT" \
  -o jsonpath='{.items[0].metadata.name}')
if [ -z "$POD_NAME" ]; then
  echo "[backfill] 실제 파드를 찾지 못했습니다. $DEPLOYMENT가 떠있는지 확인하세요." >&2
  exit 1
fi
echo "[backfill] 대상 파드: $POD_NAME"

echo "[backfill] 더미 이력 생성 중 (최근 ${DAYS}일치)..."
python3 "$SCRIPT_DIR/generate_krr_dummy_history.py" \
  --namespace "$NAMESPACE" --deployment "$DEPLOYMENT" --pod "$POD_NAME" \
  --days "$DAYS" --output "$WORKDIR/history.om"

if ! command -v promtool >/dev/null 2>&1; then
  echo "[backfill] promtool이 로컬 PATH에 없습니다. Prometheus 릴리즈(https://github.com/prometheus/prometheus/releases)에서 받아 설치하세요." >&2
  exit 1
fi

echo "[backfill] TSDB 블록 생성 중..."
promtool tsdb create-blocks-from openmetrics "$WORKDIR/history.om" "$WORKDIR/blocks"

echo "[backfill] Prometheus 파드($PROM_NAMESPACE/$PROM_POD)로 블록 복사 중..."
for block in "$WORKDIR"/blocks/*/; do
  block_name="$(basename "$block")"
  kubectl cp "$block" "$PROM_NAMESPACE/$PROM_POD:$PROM_DATA_DIR/$block_name" -c "$PROM_CONTAINER"
done

echo "[backfill] Prometheus 재시작 (새 블록은 시작 시점에만 인식됨)..."
kubectl -n "$PROM_NAMESPACE" delete pod "$PROM_POD"

echo "[backfill] 완료. 재기동 후 확인: kubectl -n $PROM_NAMESPACE get pod $PROM_POD"
