#!/usr/bin/env python3
"""Collect one Bank of Anthos KRR validation run without storing secrets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WORKLOADS = (
    ("frontend/mak-app-rollout/mak-container", "frontend", "mak-app-rollout", "mak-container"),
    ("backend/userservice/userservice", "backend", "userservice", "userservice"),
    ("backend/userservice/worker", "backend", "userservice", "worker"),
    ("backend/contacts/contacts", "backend", "contacts", "contacts"),
    ("backend/contacts/worker", "backend", "contacts", "worker"),
    ("backend/balancereader/balancereader", "backend", "balancereader", "balancereader"),
    ("backend/balancereader/worker", "backend", "balancereader", "worker"),
    ("backend/ledgerwriter/ledgerwriter", "backend", "ledgerwriter", "ledgerwriter"),
    ("backend/ledgerwriter/worker", "backend", "ledgerwriter", "worker"),
    ("backend/transactionhistory/transactionhistory", "backend", "transactionhistory", "transactionhistory"),
    ("backend/transactionhistory/worker", "backend", "transactionhistory", "worker"),
)


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)(m|h|d|w)", value)
    if not match:
        raise argparse.ArgumentTypeError("duration must use m, h, d, or w (for example 24h)")
    return int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group(2)]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values: list[float]) -> dict[str, float | None]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return {"avg": None, "p95": None, "max": None}
    return {
        "avg": round(statistics.fmean(clean), 6),
        "p95": round(percentile(clean, 0.95), 6),
        "max": round(max(clean), 6),
    }


class Prometheus:
    def __init__(self, base_url: str, start: datetime, end: datetime, step: str):
        self.base_url = base_url.rstrip("/")
        self.start = start
        self.end = end
        self.step = step

    def range_values(self, query: str) -> list[float]:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "start": self.start.isoformat().replace("+00:00", "Z"),
                "end": self.end.isoformat().replace("+00:00", "Z"),
                "step": self.step,
            }
        )
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/query_range?{params}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        totals: dict[float, float] = {}
        for series in payload.get("data", {}).get("result", []):
            for timestamp, raw in series.get("values", []):
                value = float(raw)
                if math.isfinite(value):
                    totals[float(timestamp)] = totals.get(float(timestamp), 0.0) + value
        return [totals[key] for key in sorted(totals)]

    def range_stats(self, query: str) -> dict[str, float | None]:
        return stats(self.range_values(query))

    def instant_value(self, query: str) -> float | None:
        params = urllib.parse.urlencode({
            "query": query,
            "time": self.end.isoformat().replace("+00:00", "Z"),
        })
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/query?{params}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        values = []
        for series in payload.get("data", {}).get("result", []):
            raw = series.get("value", [None, None])[1]
            if raw is not None and math.isfinite(float(raw)):
                values.append(float(raw))
        return sum(values) if values else None


def selector(namespace: str, workload: str, container: str) -> str:
    pod_regex = f"^{workload}-.*"
    return f'namespace="{namespace}",pod=~"{pod_regex}",container="{container}"'


def window_seconds(start: datetime, end: datetime) -> int:
    return max(1, int((end - start).total_seconds()))


def collect_workload(prom: Prometheus, namespace: str, workload: str, container: str) -> dict[str, Any]:
    labels = selector(namespace, workload, container)
    window = window_seconds(prom.start, prom.end)
    cpu_usage = f'sum(rate(container_cpu_usage_seconds_total{{{labels}}}[5m]))'
    memory_usage = f'sum(container_memory_working_set_bytes{{{labels}}})'
    cpu_request = (
        f'max(kube_pod_container_resource_requests{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="cpu"}})'
    )
    memory_request = (
        f'max(kube_pod_container_resource_requests{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="memory"}})'
    )
    cpu_limit = (
        f'max(kube_pod_container_resource_limits{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="cpu"}})'
    )
    memory_limit = (
        f'max(kube_pod_container_resource_limits{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="memory"}})'
    )
    cpu_ratio = (
        f'sum(rate(container_cpu_usage_seconds_total{{{labels}}}[5m])) / '
        f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="cpu"}})'
    )
    memory_ratio = (
        f'sum(container_memory_working_set_bytes{{{labels}}}) / '
        f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",resource="memory"}})'
    )
    throttle = (
        f'sum(rate(container_cpu_cfs_throttled_periods_total{{{labels}}}[5m])) / '
        f'clamp_min(sum(rate(container_cpu_cfs_periods_total{{{labels}}}[5m])), 1e-9)'
    )
    restart = (
        f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}"}}[{window}s])) or vector(0)'
    )
    oom = (
        f'sum(max_over_time(kube_pod_container_status_last_terminated_reason{{namespace="{namespace}",'
        f'pod=~"^{workload}-.*",container="{container}",reason="OOMKilled"}}[{window}s])) or vector(0)'
    )
    replicas = f'count(kube_pod_info{{namespace="{namespace}",pod=~"^{workload}-.*"}})'

    return {
        "namespace": namespace,
        "workload": workload,
        "container": container,
        "cpu_usage_cores": prom.range_stats(cpu_usage),
        "memory_working_set_bytes": prom.range_stats(memory_usage),
        "cpu_request_cores_per_replica": prom.range_stats(cpu_request),
        "memory_request_bytes_per_replica": prom.range_stats(memory_request),
        "cpu_limit_cores_per_replica": prom.range_stats(cpu_limit),
        "memory_limit_bytes_per_replica": prom.range_stats(memory_limit),
        "cpu_usage_request_ratio": prom.range_stats(cpu_ratio),
        "memory_usage_request_ratio": prom.range_stats(memory_ratio),
        "cpu_throttling_ratio": prom.range_stats(throttle),
        "restart_increase": prom.instant_value(restart),
        "oom_killed_pods": prom.instant_value(oom),
        "replicas": prom.range_stats(replicas),
    }


def metric_values(summary: dict[str, Any], name: str) -> dict[str, Any]:
    return summary.get("metrics", {}).get(name, {}).get("values", {}) or {}


def load_k6_summary(path: Path) -> dict[str, Any]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    metrics = summary.get("metrics", {})
    offered_flows = metric_values(summary, "boa_offered_flows")
    offered = metric_values(summary, "boa_offered_requests")
    successful = metric_values(summary, "boa_successful_requests")
    system = metric_values(summary, "boa_system_failures")
    business = metric_values(summary, "boa_business_failures")
    intentional = metric_values(summary, "boa_intentional_4xx")
    latency = metric_values(summary, "boa_e2e_latency_ms")
    flow = metric_values(summary, "boa_flow_success")
    dropped = metric_values(summary, "dropped_iterations")

    offered_count = int(offered.get("count", 0))
    success_count = int(successful.get("count", 0))
    return {
        "offered_flows": int(offered_flows.get("count", 0)),
        "offered_flow_rps": offered_flows.get("rate"),
        "offered_requests": offered_count,
        "offered_rps": offered.get("rate"),
        "successful_requests": success_count,
        "successful_rps": successful.get("rate"),
        "system_failures": int(system.get("count", 0)),
        "business_failures": int(business.get("count", 0)),
        "dropped_iterations": int(dropped.get("count", 0)),
        "intentional_4xx": int(intentional.get("count", 0)),
        "system_error_rate": (int(system.get("count", 0)) / offered_count) if offered_count else None,
        "business_failure_rate": (int(business.get("count", 0)) / offered_count) if offered_count else None,
        "flow_success_rate": flow.get("rate"),
        "latency_ms": {
            "p50": latency.get("med"),
            "p95": latency.get("p(95)"),
            "p99": latency.get("p(99)"),
            "avg": latency.get("avg"),
            "max": latency.get("max"),
        },
        "summary_metadata": {
            key: summary.get(key)
            for key in ("schema_version", "run_id", "phase", "scenario", "scenario_version", "profile", "time_scale", "cycles", "request_timeout", "auth_mode", "scenario_schedule", "finished_at")
        },
    }


def load_json(path: Path | None) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def write_csv(path: Path, report: dict[str, Any]) -> None:
    fields = [
        "identifier", "cpu_request_cores_avg", "memory_request_bytes_avg",
        "cpu_limit_cores_avg", "memory_limit_bytes_avg",
        "cpu_usage_avg", "cpu_usage_p95", "cpu_usage_max",
        "memory_usage_avg", "memory_usage_p95", "memory_usage_max",
        "cpu_throttle_avg", "cpu_throttle_p95", "oom", "restarts",
        "replicas_avg", "replicas_max",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for identifier, item in report["workloads"].items():
            writer.writerow({
                "identifier": identifier,
                "cpu_request_cores_avg": item["cpu_request_cores_per_replica"]["avg"],
                "memory_request_bytes_avg": item["memory_request_bytes_per_replica"]["avg"],
                "cpu_limit_cores_avg": item["cpu_limit_cores_per_replica"]["avg"],
                "memory_limit_bytes_avg": item["memory_limit_bytes_per_replica"]["avg"],
                "cpu_usage_avg": item["cpu_usage_cores"]["avg"],
                "cpu_usage_p95": item["cpu_usage_cores"]["p95"],
                "cpu_usage_max": item["cpu_usage_cores"]["max"],
                "memory_usage_avg": item["memory_working_set_bytes"]["avg"],
                "memory_usage_p95": item["memory_working_set_bytes"]["p95"],
                "memory_usage_max": item["memory_working_set_bytes"]["max"],
                "cpu_throttle_avg": item["cpu_throttling_ratio"]["avg"],
                "cpu_throttle_p95": item["cpu_throttling_ratio"]["p95"],
                "oom": item["oom_killed_pods"],
                "restarts": item["restart_increase"],
                "replicas_avg": item["replicas"]["avg"],
                "replicas_max": item["replicas"]["max"],
            })

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", choices=("pre", "post", "smoke", "pilot"), required=True)
    parser.add_argument("--start", type=utc, required=True)
    parser.add_argument("--end", type=utc, required=True)
    parser.add_argument("--prometheus-url", required=True)
    parser.add_argument("--application-commit", required=True)
    parser.add_argument("--gitops-commit", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--scenario-file", type=Path, required=True)
    parser.add_argument("--krr-history-duration", required=True)
    parser.add_argument("--krr-executed-at", type=utc)
    parser.add_argument("--krr-max-end-offset-seconds", type=int, default=300)
    parser.add_argument("--k6-summary", type=Path, required=True)
    parser.add_argument("--equivalence-metadata", type=Path, required=True)
    parser.add_argument("--worker-node-query", default="count(kube_node_info)")
    parser.add_argument("--karpenter-node-query", default='count(count by (node) (kube_node_labels{label_karpenter_sh_nodepool!=""}))')
    parser.add_argument("--krr-results", type=Path)
    parser.add_argument("--step", default="60s")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    args = parser.parse_args()

    if args.end <= args.start:
        parser.error("--end must be later than --start")
    if args.krr_results and not args.krr_executed_at:
        parser.error("--krr-executed-at is required with --krr-results")
    krr_window = None
    if args.krr_executed_at:
        history_seconds = parse_duration_seconds(args.krr_history_duration)
        experiment_seconds = int((args.end - args.start).total_seconds())
        end_offset = int((args.krr_executed_at - args.end).total_seconds())
        if abs(history_seconds - experiment_seconds) > args.krr_max_end_offset_seconds:
            parser.error("KRR history duration does not match the experiment duration")
        if abs(end_offset) > args.krr_max_end_offset_seconds:
            parser.error("KRR execution time is too far from the experiment end")
        effective_start = args.krr_executed_at - timedelta(seconds=history_seconds)
        krr_window = {
            "executed_at": args.krr_executed_at.isoformat().replace("+00:00", "Z"),
            "effective_started_at": effective_start.isoformat().replace("+00:00", "Z"),
            "effective_ended_at": args.krr_executed_at.isoformat().replace("+00:00", "Z"),
            "experiment_end_offset_seconds": end_offset,
            "max_allowed_end_offset_seconds": args.krr_max_end_offset_seconds,
        }
    scenario_hash = hashlib.sha256(args.scenario_file.read_bytes()).hexdigest()
    k6 = load_k6_summary(args.k6_summary)
    if k6["summary_metadata"].get("run_id") != args.run_id:
        parser.error("k6 summary run_id does not match --run-id")
    if k6["summary_metadata"].get("phase") != args.phase:
        parser.error("k6 summary phase does not match --phase")

    prom = Prometheus(args.prometheus_url, args.start, args.end, args.step)
    workloads: dict[str, Any] = {}
    query_errors: dict[str, str] = {}
    for identifier, namespace, workload, container in WORKLOADS:
        try:
            workloads[identifier] = collect_workload(prom, namespace, workload, container)
        except Exception as exc:
            query_errors[identifier] = str(exc)

    node_stats = {}
    for name, query in (("worker_nodes", args.worker_node_query), ("karpenter_nodes", args.karpenter_node_query)):
        try:
            node_stats[name] = prom.range_stats(query)
        except Exception as exc:
            query_errors[name] = str(exc)
            node_stats[name] = {"avg": None, "p95": None, "max": None}

    duration = (args.end - args.start).total_seconds()
    report = {
        "schema_version": "1.0",
        "run_id": args.run_id,
        "phase": args.phase,
        "started_at": args.start.isoformat().replace("+00:00", "Z"),
        "ended_at": args.end.isoformat().replace("+00:00", "Z"),
        "duration_seconds": duration,
        "application_commit": args.application_commit,
        "gitops_commit": args.gitops_commit,
        "scenario": args.scenario,
        "scenario_sha256": scenario_hash,
        "krr_history_duration": args.krr_history_duration,
        "krr_analysis_window": krr_window,
        "equivalence": load_json(args.equivalence_metadata),
        "http": k6,
        "workloads": workloads,
        "nodes": node_stats,
        "krr_recommendations": load_json(args.krr_results),
        "collection_warnings": query_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.csv_output:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.csv_output, report)
    if query_errors:
        print(f"warning: {len(query_errors)} workload metric queries failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
