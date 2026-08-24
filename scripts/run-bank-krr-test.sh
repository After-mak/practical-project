#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DEPLOY_REPO="${BANK_DEPLOY_REPO:-$ROOT_DIR/../mak-argocd-deploy}"
CHART_DIR="${BANK_CHART_DIR:-$DEPLOY_REPO/charts/mak-app}"
SCENARIO_FILE="$CHART_DIR/files/bank-of-anthos-long-run.js"
RESULTS_ROOT="${BANK_RESULTS_ROOT:-$ROOT_DIR/k6/results}"
NAMESPACE="${BANK_NAMESPACE:-frontend}"
PROMETHEUS_NAMESPACE="${PROMETHEUS_NAMESPACE:-prometheus}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-service/thanos-query}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:$PROMETHEUS_LOCAL_PORT}"
PROMETHEUS_PORT_FORWARD="${PROMETHEUS_PORT_FORWARD:-1}"
POLL_SECONDS="${POLL_SECONDS:-30}"
RESULTS_PVC="${RESULTS_PVC:-bank-loadgen-results}"
CREDENTIALS_SECRET="${CREDENTIALS_SECRET:-bank-loadgen-credentials}"
LOADGEN_IMAGE="${LOADGEN_IMAGE:-grafana/k6:0.54.0}"
LOW_RPS="${LOW_RPS:-1}"
NORMAL_RPS="${NORMAL_RPS:-10}"
PEAK_RPS="${PEAK_RPS:-25}"
SPIKE_RPS="${SPIKE_RPS:-40}"
RECOVERY_RPS="${RECOVERY_RPS:-3}"
MAX_VUS="${MAX_VUS:-1500}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-10s}"
AUTH_MODE="${AUTH_MODE:-shared}"
PAYMENT_PERCENT="${PAYMENT_PERCENT:-0}"
PAYMENT_AMOUNT="${PAYMENT_AMOUNT:-0.01}"
SCENARIO_NAME="${SCENARIO_NAME:-boa-long-cycle-v1}"
SCENARIO_VERSION="${SCENARIO_VERSION:-v1}"
KEEP_JOB="${KEEP_JOB:-0}"
COPY_RAW="${COPY_RAW:-0}"

LOG_PID=""
PORT_FORWARD_PID=""

usage() {
  cat <<'EOF'
Bank of Anthos KRR 장기 트래픽 실행기

사용법:
  scripts/run-bank-krr-test.sh run smoke|pre|post
  scripts/run-bank-krr-test.sh config smoke|pre|post
  scripts/run-bank-krr-test.sh status
  RUN_ID=<id> scripts/run-bank-krr-test.sh stop
  scripts/run-bank-krr-test.sh compare <pre-result-dir> <post-result-dir>

Makefile 단축 명령:
  make bank-smoke
  DB_STATE_ID=<동일한-snapshot-id> make bank-pre
  DB_STATE_ID=<동일한-snapshot-id> make bank-post
  make bank-status [RUN_ID=<id>]
  make bank-stop RUN_ID=<id>
  make bank-compare PRE_RUN=k6/results/<pre-id> POST_RUN=k6/results/<post-id>

기본 실행 시간:
  smoke: PROFILE=smoke, TIME_SCALE=1, CYCLES=1 (30분)
  pre/post: PROFILE=long, TIME_SCALE=0.75, CYCLES=3 (각 3시간)

주요 선택 환경변수:
  RUN_ID                 실행 ID(미지정 시 UTC 시각으로 자동 생성)
  DB_STATE_ID            PRE/POST에서 필수인 동일 DB snapshot/seed 식별자
  BANK_DEPLOY_REPO       기본값: ../mak-argocd-deploy
  EQUIVALENCE_FILE       직접 작성한 동등성 metadata JSON
  PROMETHEUS_URL         외부 URL 사용 시 PROMETHEUS_PORT_FORWARD=0도 설정
  COPY_RAW=1             큰 k6 raw JSON도 PVC에서 복사
  KEEP_JOB=1             결과 수집 후 Job/ConfigMap 유지

KRR 권장값 적용은 이 스크립트가 수행하지 않는다. PRE 완료 후 별도로 적용하고
Rollout 안정화를 확인한 다음 같은 DB_STATE_ID와 부하 설정으로 POST를 실행한다.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '[bank-krr] %s\n' "$*"
}

cleanup_processes() {
  if [[ -n "$LOG_PID" ]]; then
    kill "$LOG_PID" 2>/dev/null || true
    wait "$LOG_PID" 2>/dev/null || true
  fi
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" 2>/dev/null || true
    wait "$PORT_FORWARD_PID" 2>/dev/null || true
  fi
}
trap cleanup_processes EXIT

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "필수 명령을 찾을 수 없습니다: $1"
}

safe_run_id() {
  printf '%s' "$1" |
    tr '[:upper:]' '[:lower:]' |
    sed -E 's/[^a-z0-9-]/-/g; s/^-+//; s/-+$//' |
    cut -c1-32
}

configure_phase() {
  PHASE="$1"
  case "$PHASE" in
    smoke)
      PROFILE="${PROFILE:-smoke}"
      TIME_SCALE="${TIME_SCALE:-1}"
      CYCLES="${CYCLES:-1}"
      EXPECTED_DURATION_SECONDS=1800
      KRR_HISTORY_DURATION="${KRR_HISTORY_DURATION:-30m}"
      ;;
    pre|post)
      PROFILE="${PROFILE:-long}"
      TIME_SCALE="${TIME_SCALE:-0.75}"
      CYCLES="${CYCLES:-3}"
      EXPECTED_DURATION_SECONDS=10800
      KRR_HISTORY_DURATION="${KRR_HISTORY_DURATION:-3h}"
      ;;
    *) die "phase는 smoke, pre, post 중 하나여야 합니다: $PHASE" ;;
  esac

  if [[ -n "${TEST_DURATION_SECONDS:-}" ]]; then
    EXPECTED_DURATION_SECONDS="$TEST_DURATION_SECONDS"
  elif [[ "$TIME_SCALE" != "1" || "$CYCLES" != "1" ]]; then
    local base_seconds=4800
    [[ "$PROFILE" == "smoke" ]] && base_seconds=1800
    EXPECTED_DURATION_SECONDS="$(
      awk -v base="$base_seconds" -v scale="$TIME_SCALE" -v cycles="$CYCLES" \
        'BEGIN { printf "%d", base * scale * cycles + 0.5 }'
    )"
  fi
  ACTIVE_DEADLINE_SECONDS="${ACTIVE_DEADLINE_SECONDS:-$((EXPECTED_DURATION_SECONDS + 1800))}"
}

print_config() {
  cat <<EOF
phase=$PHASE
profile=$PROFILE
time_scale=$TIME_SCALE
cycles=$CYCLES
expected_duration_seconds=$EXPECTED_DURATION_SECONDS
krr_history_duration=$KRR_HISTORY_DURATION
namespace=$NAMESPACE
chart_dir=$CHART_DIR
results_root=$RESULTS_ROOT
EOF
}

preflight() {
  require_command kubectl
  require_command helm
  require_command python3
  require_command git
  require_command curl
  [[ -f "$CHART_DIR/Chart.yaml" ]] || die "Helm chart를 찾을 수 없습니다: $CHART_DIR"
  [[ -f "$SCENARIO_FILE" ]] || die "k6 시나리오를 찾을 수 없습니다: $SCENARIO_FILE"

  kubectl cluster-info >/dev/null
  kubectl get namespace "$NAMESPACE" >/dev/null
  kubectl -n "$NAMESPACE" get secret "$CREDENTIALS_SECRET" >/dev/null
  kubectl -n "$NAMESPACE" get service mak-app-active >/dev/null
  kubectl -n "$NAMESPACE" get endpoints mak-app-active \
    -o jsonpath='{.subsets[0].addresses[0].ip}' | grep -q . \
    || die "mak-app-active Service에 Ready endpoint가 없습니다"
  kubectl -n "$PROMETHEUS_NAMESPACE" get "$PROMETHEUS_SERVICE" >/dev/null
  kubectl -n "$PROMETHEUS_NAMESPACE" get endpoints "${PROMETHEUS_SERVICE#service/}" \
    -o jsonpath='{.subsets[0].addresses[0].ip}' | grep -q . \
    || die "Prometheus/Thanos Query Service에 Ready endpoint가 없습니다"
  kubectl -n "$NAMESPACE" wait --for=condition=Ready pod --all --timeout=60s >/dev/null
  kubectl -n backend wait --for=condition=Ready pod --all --timeout=60s >/dev/null

  if kubectl -n "$NAMESPACE" get rollout mak-app-rollout >/dev/null 2>&1; then
    local paused rollout_phase
    paused="$(kubectl -n "$NAMESPACE" get rollout mak-app-rollout -o jsonpath='{.spec.paused}')"
    rollout_phase="$(kubectl -n "$NAMESPACE" get rollout mak-app-rollout -o jsonpath='{.status.phase}')"
    [[ "$paused" != "true" ]] || die "frontend Rollout이 pause 상태입니다"
    [[ "$rollout_phase" == "Healthy" ]] \
      || die "frontend Rollout 상태가 Healthy가 아닙니다: ${rollout_phase:-unknown}"
  fi

  if kubectl -n "$NAMESPACE" get jobs -l app=bank-loadgen -o json |
      python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if any(i.get("status",{}).get("active",0) for i in d["items"]) else 1)'; then
    die "이미 실행 중인 bank-loadgen Job이 있습니다. make bank-status로 확인하세요"
  fi

  if [[ "$PHASE" == "pre" || "$PHASE" == "post" ]]; then
    [[ -n "${DB_STATE_ID:-}" || -n "${EQUIVALENCE_FILE:-}" ]] \
      || die "PRE/POST에는 DB_STATE_ID 또는 EQUIVALENCE_FILE이 필요합니다"
    [[ -z "$(git -C "$DEPLOY_REPO" status --porcelain)" ]] \
      || die "배포 저장소에 커밋되지 않은 변경이 있습니다: $DEPLOY_REPO"
  fi
}

render_manifest() {
  local output="$1"
  helm template bank-krr "$CHART_DIR" \
    --namespace "$NAMESPACE" \
    --show-only templates/7-loadgen.yaml \
    --set components.backend=false \
    --set components.frontend=true \
    --set loadgen.enabled=true \
    --set-string loadgen.runId="$RUN_ID" \
    --set-string loadgen.phase="$PHASE" \
    --set-string loadgen.profile="$PROFILE" \
    --set-string loadgen.timeScale="$TIME_SCALE" \
    --set-string loadgen.cycles="$CYCLES" \
    --set-string loadgen.lowRps="$LOW_RPS" \
    --set-string loadgen.normalRps="$NORMAL_RPS" \
    --set-string loadgen.peakRps="$PEAK_RPS" \
    --set-string loadgen.spikeRps="$SPIKE_RPS" \
    --set-string loadgen.recoveryRps="$RECOVERY_RPS" \
    --set-string loadgen.maxVUs="$MAX_VUS" \
    --set-string loadgen.requestTimeout="$REQUEST_TIMEOUT" \
    --set-string loadgen.authMode="$AUTH_MODE" \
    --set-string loadgen.paymentPercent="$PAYMENT_PERCENT" \
    --set-string loadgen.paymentAmount="$PAYMENT_AMOUNT" \
    --set-string loadgen.scenarioName="$SCENARIO_NAME" \
    --set-string loadgen.scenarioVersion="$SCENARIO_VERSION" \
    --set-string loadgen.image="$LOADGEN_IMAGE" \
    --set loadgen.prometheusRemoteWriteEnabled=false \
    --set loadgen.activeDeadlineSeconds="$ACTIVE_DEADLINE_SECONDS" \
    --set-string loadgen.persistence.claimName="$RESULTS_PVC" \
    --set-string loadgen.credentialsSecret.name="$CREDENTIALS_SECRET" \
    >"$output"
}

wait_for_job() {
  local job_name="$1" status_file="$2"
  local deadline=$(( $(date +%s) + ACTIVE_DEADLINE_SECONDS + 300 ))
  printf 'timestamp\tactive\tsucceeded\tfailed\tfrontend_pods\n' >"$status_file"

  while true; do
    local now active succeeded failed frontend_pods
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    active="$(kubectl -n "$NAMESPACE" get job "$job_name" -o jsonpath='{.status.active}')"
    succeeded="$(kubectl -n "$NAMESPACE" get job "$job_name" -o jsonpath='{.status.succeeded}')"
    failed="$(kubectl -n "$NAMESPACE" get job "$job_name" -o jsonpath='{.status.failed}')"
    frontend_pods="$(
      kubectl -n "$NAMESPACE" get pods -l app=mak-app --no-headers 2>/dev/null |
        wc -l | tr -d ' '
    )"
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$now" "${active:-0}" "${succeeded:-0}" "${failed:-0}" "$frontend_pods" |
      tee -a "$status_file"
    [[ "${succeeded:-0}" -ge 1 ]] && return 0
    [[ "${failed:-0}" -ge 1 ]] && return 2
    [[ "$(date +%s)" -lt "$deadline" ]] || return 124
    sleep "$POLL_SECONDS"
  done
}

copy_results() {
  local run_dir="$1" job_name="$2"
  local reader="bank-results-reader-$SAFE_RUN_ID"
  local reader_manifest="$run_dir/result-reader.yaml"
  local node_name
  node_name="$(
    kubectl -n "$NAMESPACE" get pod -l "job-name=$job_name" \
      -o jsonpath='{.items[0].spec.nodeName}'
  )"
  [[ -n "$node_name" ]] || die "Load Generator Pod의 nodeName을 확인할 수 없습니다"

  cat >"$reader_manifest" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $reader
  namespace: $NAMESPACE
  labels:
    app: bank-results-reader
    run-id: $SAFE_RUN_ID
spec:
  restartPolicy: Never
  nodeName: $node_name
  containers:
    - name: reader
      image: busybox:1.36
      command: ["sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: results
          mountPath: /results
  volumes:
    - name: results
      persistentVolumeClaim:
        claimName: $RESULTS_PVC
EOF
  kubectl -n "$NAMESPACE" delete pod "$reader" --ignore-not-found --wait=true >/dev/null
  kubectl apply -f "$reader_manifest" >/dev/null
  kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$reader" --timeout=120s >/dev/null
  kubectl -n "$NAMESPACE" cp \
    "$reader:/results/summary-$SAFE_RUN_ID.json" "$run_dir/summary.json"
  kubectl -n "$NAMESPACE" cp \
    "$reader:/results/k6-summary-$SAFE_RUN_ID.json" "$run_dir/k6-summary.json"
  if [[ "$COPY_RAW" == "1" ]]; then
    kubectl -n "$NAMESPACE" cp \
      "$reader:/results/raw-$SAFE_RUN_ID.json" "$run_dir/raw.json"
  fi
  kubectl -n "$NAMESPACE" delete pod "$reader" --wait=true >/dev/null
}

generate_equivalence() {
  local run_dir="$1"
  if [[ -n "${EQUIVALENCE_FILE:-}" ]]; then
    [[ -f "$EQUIVALENCE_FILE" ]] \
      || die "EQUIVALENCE_FILE을 찾을 수 없습니다: $EQUIVALENCE_FILE"
    cp "$EQUIVALENCE_FILE" "$run_dir/equivalence.json"
    APPLICATION_COMMIT="${APPLICATION_COMMIT:-equivalence-file}"
    return
  fi

  kubectl get rollout,deployment -n "$NAMESPACE" -o json >"$run_dir/workloads-frontend.json"
  kubectl get deployment -n backend -o json >"$run_dir/workloads-backend.json"
  kubectl get scaledobject -A -o json >"$run_dir/autoscaling.json" 2>/dev/null \
    || printf '{"items":[]}\n' >"$run_dir/autoscaling.json"
  kubectl get nodepool -o json >"$run_dir/nodepools.json" 2>/dev/null \
    || printf '{"items":[]}\n' >"$run_dir/nodepools.json"

  APPLICATION_COMMIT="$(
    RUN_DIR="$run_dir" DB_STATE_ID="${DB_STATE_ID:-smoke-uncontrolled}" \
      PROFILE="$PROFILE" TIME_SCALE="$TIME_SCALE" CYCLES="$CYCLES" \
      LOW_RPS="$LOW_RPS" NORMAL_RPS="$NORMAL_RPS" PEAK_RPS="$PEAK_RPS" \
      SPIKE_RPS="$SPIKE_RPS" RECOVERY_RPS="$RECOVERY_RPS" \
      PAYMENT_PERCENT="$PAYMENT_PERCENT" LOADGEN_IMAGE="$LOADGEN_IMAGE" \
      python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["RUN_DIR"])
images = {}
for namespace, filename in (
    ("frontend", "workloads-frontend.json"),
    ("backend", "workloads-backend.json"),
):
    for item in json.loads((root / filename).read_text()).get("items", []):
        kind = item.get("kind", "Workload")
        name = item.get("metadata", {}).get("name", "unknown")
        template = item.get("spec", {}).get("template", {})
        for container in template.get("spec", {}).get("containers", []):
            key = f"{namespace}/{kind}/{name}/{container.get('name', 'unknown')}"
            images[key] = container.get("image", "")

scaled = []
for item in json.loads((root / "autoscaling.json").read_text()).get("items", []):
    spec = item.get("spec", {})
    scaled.append({
        "namespace": item.get("metadata", {}).get("namespace"),
        "name": item.get("metadata", {}).get("name"),
        "min": spec.get("minReplicaCount"),
        "max": spec.get("maxReplicaCount"),
        "triggers": sorted(t.get("type", "") for t in spec.get("triggers", [])),
    })

node_pools = []
for item in json.loads((root / "nodepools.json").read_text()).get("items", []):
    spec = item.get("spec", {})
    node_pools.append({
        "name": item.get("metadata", {}).get("name"),
        "limits": spec.get("limits", {}),
        "requirements": spec.get("template", {}).get("spec", {}).get("requirements", []),
    })

canonical_images = json.dumps(images, sort_keys=True, separators=(",", ":"))
application_commit = (
    "images-sha256:" + hashlib.sha256(canonical_images.encode()).hexdigest()
)
metadata = {
    "application_image": images,
    "loadgen_image": os.environ["LOADGEN_IMAGE"],
    "scenario_config": {
        "profile": os.environ["PROFILE"],
        "time_scale": os.environ["TIME_SCALE"],
        "cycles": os.environ["CYCLES"],
        "low_rps": os.environ["LOW_RPS"],
        "normal_rps": os.environ["NORMAL_RPS"],
        "peak_rps": os.environ["PEAK_RPS"],
        "spike_rps": os.environ["SPIKE_RPS"],
        "recovery_rps": os.environ["RECOVERY_RPS"],
        "payment_percent": os.environ["PAYMENT_PERCENT"],
    },
    "db_state_id": os.environ["DB_STATE_ID"],
    "autoscaling": sorted(
        scaled, key=lambda item: (item["namespace"] or "", item["name"] or "")
    ),
    "node_pool": sorted(node_pools, key=lambda item: item["name"] or ""),
}
(root / "equivalence.json").write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n"
)
print(application_commit)
PY
  )"
  rm -f \
    "$run_dir/workloads-frontend.json" \
    "$run_dir/workloads-backend.json" \
    "$run_dir/autoscaling.json" \
    "$run_dir/nodepools.json"
  APPLICATION_COMMIT="${APPLICATION_COMMIT_OVERRIDE:-$APPLICATION_COMMIT}"
}

start_prometheus_access() {
  if [[ "$PROMETHEUS_PORT_FORWARD" == "1" ]]; then
    kubectl -n "$PROMETHEUS_NAMESPACE" port-forward \
      "$PROMETHEUS_SERVICE" "$PROMETHEUS_LOCAL_PORT:9090" \
      >"$RUN_DIR/prometheus-port-forward.log" 2>&1 &
    PORT_FORWARD_PID=$!
  fi

  local attempts=0
  until curl --fail --silent --show-error "$PROMETHEUS_URL/-/ready" >/dev/null; do
    attempts=$((attempts + 1))
    [[ "$attempts" -lt 30 ]] \
      || die "Prometheus/Thanos Query에 연결할 수 없습니다: $PROMETHEUS_URL"
    sleep 1
  done
}

collect_metrics() {
  local run_dir="$1" start="$2" end="$3"
  local gitops_commit
  gitops_commit="$(git -C "$DEPLOY_REPO" rev-parse HEAD)"
  local args=(
    python3 "$ROOT_DIR/k6/collect_bank_krr_run.py"
    --run-id "$RUN_ID"
    --phase "$PHASE"
    --start "$start"
    --end "$end"
    --prometheus-url "$PROMETHEUS_URL"
    --application-commit "$APPLICATION_COMMIT"
    --gitops-commit "$gitops_commit"
    --scenario "$SCENARIO_NAME"
    --scenario-file "$SCENARIO_FILE"
    --krr-history-duration "$KRR_HISTORY_DURATION"
    --k6-summary "$run_dir/summary.json"
    --equivalence-metadata "$run_dir/equivalence.json"
    --output "$run_dir/collected.json"
    --csv-output "$run_dir/collected.csv"
  )
  if [[ -n "${KRR_RESULTS:-}" ]]; then
    [[ -f "$KRR_RESULTS" ]] || die "KRR_RESULTS 파일을 찾을 수 없습니다: $KRR_RESULTS"
    [[ -n "${KRR_EXECUTED_AT:-}" ]] \
      || die "KRR_RESULTS 사용 시 KRR_EXECUTED_AT이 필요합니다"
    args+=(--krr-results "$KRR_RESULTS" --krr-executed-at "$KRR_EXECUTED_AT")
  fi
  "${args[@]}"
}

evaluate_run() {
  local run_dir="$1"
  python3 - "$run_dir/collected.json" "$run_dir/verdict.json" <<'PY'
import json
import sys
from pathlib import Path

source = json.loads(Path(sys.argv[1]).read_text())
http = source["http"]
workloads = list(source.get("workloads", {}).values())


def values(path):
    result = []
    for item in workloads:
        value = item
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        result.append(value)
    return result


throttle_avg = values(("cpu_throttling_ratio", "avg"))
throttle_p95 = values(("cpu_throttling_ratio", "p95"))
oom = values(("oom_killed_pods",))
restarts = values(("restart_increase",))
checks = {
    "metrics_complete": len(workloads) == 11 and not source.get("collection_warnings"),
    "system_error_rate": (
        http.get("system_error_rate") is not None
        and http["system_error_rate"] < 0.01
    ),
    "business_failure_rate": (
        http.get("business_failure_rate") is not None
        and http["business_failure_rate"] < 0.01
    ),
    "dropped_iterations": int(http.get("dropped_iterations", -1)) == 0,
    "cpu_throttling_avg": (
        bool(throttle_avg)
        and all(v is not None and v < 0.05 for v in throttle_avg)
    ),
    "cpu_throttling_p95": (
        bool(throttle_p95)
        and all(v is not None and v < 0.20 for v in throttle_p95)
    ),
    "oom": bool(oom) and all(v is not None and float(v) == 0 for v in oom),
    "restarts": (
        bool(restarts)
        and all(v is not None and float(v) == 0 for v in restarts)
    ),
}
result = {
    "run_id": source["run_id"],
    "phase": source["phase"],
    "verdict": "PASS" if all(checks.values()) else "FAIL",
    "checks": checks,
}
Path(sys.argv[2]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(result["verdict"])
raise SystemExit(0 if result["verdict"] == "PASS" else 2)
PY
}

run_phase() {
  configure_phase "$1"
  preflight
  RUN_ID="${RUN_ID:-boa-$PHASE-$(date -u +%Y%m%d-%H%M%S)}"
  SAFE_RUN_ID="$(safe_run_id "$RUN_ID")"
  [[ -n "$SAFE_RUN_ID" ]] \
    || die "RUN_ID를 Kubernetes 이름으로 변환할 수 없습니다: $RUN_ID"
  RUN_DIR="$RESULTS_ROOT/$RUN_ID"
  [[ ! -e "$RUN_DIR" ]] || die "결과 디렉터리가 이미 존재합니다: $RUN_DIR"
  mkdir -p "$RUN_DIR"
  print_config | tee "$RUN_DIR/config.txt"
  render_manifest "$RUN_DIR/loadgen.yaml"

  note "Load Generator 배포: run_id=$RUN_ID"
  kubectl apply -f "$RUN_DIR/loadgen.yaml" >/dev/null
  local job_name
  job_name="$(
    kubectl -n "$NAMESPACE" get jobs \
      -l "app=bank-loadgen,run-id=$SAFE_RUN_ID" \
      -o jsonpath='{.items[0].metadata.name}'
  )"
  [[ -n "$job_name" ]] || die "생성된 Load Generator Job을 찾지 못했습니다"
  kubectl -n "$NAMESPACE" wait --for=condition=Ready pod \
    -l "job-name=$job_name" --timeout=180s >/dev/null
  kubectl -n "$NAMESPACE" logs -f "job/$job_name" >"$RUN_DIR/job.log" 2>&1 &
  LOG_PID=$!

  note "실행 중입니다. 다른 터미널에서 make bank-status RUN_ID=$RUN_ID 로 확인하세요."
  local wait_rc=0
  wait_for_job "$job_name" "$RUN_DIR/status.tsv" || wait_rc=$?
  cleanup_processes
  LOG_PID=""
  [[ "$wait_rc" -eq 0 ]] \
    || die "Load Generator Job 실패 또는 시간 초과(rc=$wait_rc). Job은 유지합니다"

  local start end
  start="$(kubectl -n "$NAMESPACE" get job "$job_name" -o jsonpath='{.status.startTime}')"
  end="$(kubectl -n "$NAMESPACE" get job "$job_name" -o jsonpath='{.status.completionTime}')"
  [[ -n "$start" && -n "$end" ]] || die "Job 시작/종료 시간을 확인할 수 없습니다"

  copy_results "$RUN_DIR" "$job_name"
  generate_equivalence "$RUN_DIR"
  start_prometheus_access
  collect_metrics "$RUN_DIR" "$start" "$end"

  local verdict_rc=0
  evaluate_run "$RUN_DIR" || verdict_rc=$?
  if [[ "$KEEP_JOB" != "1" ]]; then
    kubectl -n "$NAMESPACE" delete job "$job_name" --wait=true >/dev/null
    kubectl -n "$NAMESPACE" delete configmap \
      -l "app=bank-loadgen,run-id=$SAFE_RUN_ID" --wait=true >/dev/null
  fi
  note "결과 저장 완료: $RUN_DIR"
  [[ "$verdict_rc" -eq 0 ]] \
    || die "성공 기준 FAIL. $RUN_DIR/verdict.json을 확인하세요"
}

show_status() {
  require_command kubectl
  local selector="app=bank-loadgen"
  if [[ -n "${RUN_ID:-}" ]]; then
    selector="$selector,run-id=$(safe_run_id "$RUN_ID")"
  fi
  kubectl -n "$NAMESPACE" get jobs,pods -l "$selector" -o wide
}

stop_run() {
  require_command kubectl
  [[ -n "${RUN_ID:-}" ]] \
    || die "중단할 RUN_ID가 필요합니다: make bank-stop RUN_ID=<id>"
  local safe
  safe="$(safe_run_id "$RUN_ID")"
  [[ -n "$safe" ]] || die "RUN_ID가 올바르지 않습니다"
  kubectl -n "$NAMESPACE" delete job,configmap \
    -l "app=bank-loadgen,run-id=$safe" --ignore-not-found --wait=true
  kubectl -n "$NAMESPACE" delete pod "bank-results-reader-$safe" \
    --ignore-not-found --wait=true
  note "임시 리소스 정리 완료. PVC의 기존 결과 파일은 유지됩니다."
}

compare_runs() {
  local pre_dir="${1:-}" post_dir="${2:-}"
  [[ -n "$pre_dir" && -n "$post_dir" ]] \
    || die "PRE_RUN과 POST_RUN이 필요합니다"
  [[ "$pre_dir" = /* ]] || pre_dir="$ROOT_DIR/$pre_dir"
  [[ "$post_dir" = /* ]] || post_dir="$ROOT_DIR/$post_dir"
  [[ -f "$pre_dir/collected.json" ]] \
    || die "PRE 결과가 없습니다: $pre_dir/collected.json"
  [[ -f "$post_dir/collected.json" ]] \
    || die "POST 결과가 없습니다: $post_dir/collected.json"

  local output
  output="$RESULTS_ROOT/comparison-$(basename "$pre_dir")-vs-$(basename "$post_dir")"
  mkdir -p "$output"
  python3 "$ROOT_DIR/k6/compare_bank_krr_runs.py" \
    --pre "$pre_dir/collected.json" \
    --post "$post_dir/collected.json" \
    --thresholds "$ROOT_DIR/k6/bank-krr-success-criteria.json" \
    --json-output "$output/comparison.json" \
    --markdown-output "$output/comparison.md" \
    --csv-output "$output/comparison.csv"
  note "비교 결과: $output"
}

main() {
  local command="${1:-help}"
  case "$command" in
    help|-h|--help) usage ;;
    config)
      configure_phase "${2:-}"
      print_config
      ;;
    run) run_phase "${2:-}" ;;
    status) show_status ;;
    stop) stop_run ;;
    compare) compare_runs "${2:-}" "${3:-}" ;;
    *) die "알 수 없는 명령입니다: $command (help를 확인하세요)" ;;
  esac
}

main "$@"
