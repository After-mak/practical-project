#!/usr/bin/env python3
"""Compare equivalent Bank of Anthos PRE and POST KRR validation runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS = {
    "system_error_rate_max": 0.01,
    "business_failure_rate_max": 0.01,
    "offered_rps_deviation_max": 0.01,
    "dropped_iterations_max": 0,
    "p95_regression_max": 0.10,
    "p99_regression_max": 0.15,
    "successful_throughput_ratio_min": 0.95,
    "cpu_throttling_avg_max": 0.05,
    "cpu_throttling_p95_max": 0.20,
    "oom_increase_max": 0,
    "restart_increase_max": 0,
    "require_resource_reduction": True,
}

EQUIVALENCE_KEYS = (
    "application_image",
    "loadgen_image",
    "scenario_config",
    "db_state_id",
    "autoscaling",
    "node_pool",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(after: float | None, before: float | None) -> float | None:
    if after is None or before in (None, 0):
        return None
    return (after - before) / before


def reduction(after: float | None, before: float | None) -> float | None:
    value = ratio(after, before)
    return -value if value is not None else None


def fmt_number(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def fmt_percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def request_capacity(run: dict[str, Any], resource_key: str) -> float | None:
    items = list(run.get("workloads", {}).values())
    if len(items) != 11:
        return None
    total = 0.0
    for item in items:
        request = item.get(resource_key, {}).get("avg")
        replicas = item.get("replicas", {}).get("avg")
        if request is None or replicas is None:
            return None
        total += request * replicas
    return total


def metrics_complete(run: dict[str, Any]) -> bool:
    items = list(run.get("workloads", {}).values())
    if len(items) != 11 or run.get("collection_warnings"):
        return False
    for item in items:
        required = (
            item.get("cpu_request_cores_per_replica", {}).get("avg"),
            item.get("memory_request_bytes_per_replica", {}).get("avg"),
            item.get("cpu_throttling_ratio", {}).get("avg"),
            item.get("cpu_throttling_ratio", {}).get("p95"),
            item.get("oom_killed_pods"),
            item.get("restart_increase"),
            item.get("replicas", {}).get("avg"),
        )
        if any(value is None for value in required):
            return False
    return True


def equivalence_mismatches(pre: dict[str, Any], post: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    if pre.get("scenario") != post.get("scenario"):
        mismatches.append("scenario")
    if pre.get("scenario_sha256") != post.get("scenario_sha256"):
        mismatches.append("scenario_sha256")
    if pre.get("duration_seconds") != post.get("duration_seconds"):
        mismatches.append("duration_seconds")
    if pre.get("application_commit") != post.get("application_commit"):
        mismatches.append("application_commit")
    before = pre.get("equivalence", {})
    after = post.get("equivalence", {})
    for key in EQUIVALENCE_KEYS:
        if before.get(key) != after.get(key):
            mismatches.append(f"equivalence.{key}")
    return mismatches


def aggregate_stability(run: dict[str, Any]) -> dict[str, float | None]:
    workloads = list(run.get("workloads", {}).values())
    if not workloads:
        return {"oom": None, "restarts": None, "throttle_avg_max": None, "throttle_p95_max": None}
    oom = [item.get("oom_killed_pods") for item in workloads]
    restarts = [item.get("restart_increase") for item in workloads]
    throttle_avg = [item.get("cpu_throttling_ratio", {}).get("avg") for item in workloads]
    throttle_p95 = [item.get("cpu_throttling_ratio", {}).get("p95") for item in workloads]
    return {
        "oom": sum(float(value) for value in oom) if all(value is not None for value in oom) else None,
        "restarts": sum(float(value) for value in restarts) if all(value is not None for value in restarts) else None,
        "throttle_avg_max": max(float(value) for value in throttle_avg) if all(value is not None for value in throttle_avg) else None,
        "throttle_p95_max": max(float(value) for value in throttle_p95) if all(value is not None for value in throttle_p95) else None,
    }


def compare(pre: dict[str, Any], post: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    mismatches = equivalence_mismatches(pre, post)
    pre_http = pre["http"]
    post_http = post["http"]
    p95_change = ratio(post_http["latency_ms"].get("p95"), pre_http["latency_ms"].get("p95"))
    p99_change = ratio(post_http["latency_ms"].get("p99"), pre_http["latency_ms"].get("p99"))
    throughput_ratio = (
        post_http.get("successful_rps") / pre_http.get("successful_rps")
        if pre_http.get("successful_rps") not in (None, 0) and post_http.get("successful_rps") is not None
        else None
    )
    offered_rps_change = ratio(post_http.get("offered_rps"), pre_http.get("offered_rps"))
    pre_cpu = request_capacity(pre, "cpu_request_cores_per_replica")
    post_cpu = request_capacity(post, "cpu_request_cores_per_replica")
    pre_memory = request_capacity(pre, "memory_request_bytes_per_replica")
    post_memory = request_capacity(post, "memory_request_bytes_per_replica")
    post_stability = aggregate_stability(post)
    system_error = post_http.get("system_error_rate")
    business_failure = post_http.get("business_failure_rate")
    pre_dropped = pre_http.get("dropped_iterations")
    post_dropped = post_http.get("dropped_iterations")
    checks = {
        "equivalent_inputs": not mismatches,
        "complete_metrics": metrics_complete(pre) and metrics_complete(post),
        "system_error_rate": system_error is not None and system_error < thresholds["system_error_rate_max"],
        "business_failure_rate": business_failure is not None and business_failure < thresholds["business_failure_rate_max"],
        "offered_rps": offered_rps_change is not None and abs(offered_rps_change) <= thresholds["offered_rps_deviation_max"],
        "dropped_iterations": pre_dropped is not None and post_dropped is not None and int(pre_dropped) <= thresholds["dropped_iterations_max"] and int(post_dropped) <= thresholds["dropped_iterations_max"],
        "p95_latency": p95_change is not None and p95_change <= thresholds["p95_regression_max"],
        "p99_latency": p99_change is not None and p99_change <= thresholds["p99_regression_max"],
        "successful_throughput": throughput_ratio is not None and throughput_ratio >= thresholds["successful_throughput_ratio_min"],
        "cpu_throttling_avg": post_stability["throttle_avg_max"] is not None and post_stability["throttle_avg_max"] < thresholds["cpu_throttling_avg_max"],
        "cpu_throttling_p95": post_stability["throttle_p95_max"] is not None and post_stability["throttle_p95_max"] < thresholds["cpu_throttling_p95_max"],
        "oom": post_stability["oom"] is not None and post_stability["oom"] <= thresholds["oom_increase_max"],
        "restarts": post_stability["restarts"] is not None and post_stability["restarts"] <= thresholds["restart_increase_max"],
        "resource_reduction": pre_cpu is not None and post_cpu is not None and pre_memory is not None and post_memory is not None and (post_cpu < pre_cpu or post_memory < pre_memory),
    }
    if not thresholds.get("require_resource_reduction", True):
        checks["resource_reduction"] = True

    workloads: dict[str, Any] = {}
    for identifier in sorted(set(pre.get("workloads", {})) | set(post.get("workloads", {}))):
        before = pre.get("workloads", {}).get(identifier, {})
        after = post.get("workloads", {}).get(identifier, {})
        cpu_before = before.get("cpu_request_cores_per_replica", {}).get("avg")
        cpu_after = after.get("cpu_request_cores_per_replica", {}).get("avg")
        mem_before = before.get("memory_request_bytes_per_replica", {}).get("avg")
        mem_after = after.get("memory_request_bytes_per_replica", {}).get("avg")
        throttle_avg = after.get("cpu_throttling_ratio", {}).get("avg")
        throttle_p95 = after.get("cpu_throttling_ratio", {}).get("p95")
        oom = after.get("oom_killed_pods")
        restarts = after.get("restart_increase")
        stable = (
            throttle_avg is not None
            and throttle_p95 is not None
            and oom is not None
            and restarts is not None
            and throttle_avg < thresholds["cpu_throttling_avg_max"]
            and throttle_p95 < thresholds["cpu_throttling_p95_max"]
            and float(oom) <= thresholds["oom_increase_max"]
            and float(restarts) <= thresholds["restart_increase_max"]
        )
        workloads[identifier] = {
            "cpu_request_before": cpu_before,
            "cpu_request_after": cpu_after,
            "cpu_request_reduction": reduction(cpu_after, cpu_before),
            "memory_request_before_bytes": mem_before,
            "memory_request_after_bytes": mem_after,
            "memory_request_reduction": reduction(mem_after, mem_before),
            "post_cpu_throttling_avg": throttle_avg,
            "post_cpu_throttling_p95": throttle_p95,
            "post_oom": oom,
            "post_restarts": restarts,
            "verdict": "PASS" if stable else "FAIL",
        }

    return {
        "schema_version": "1.0",
        "pre_run_id": pre["run_id"],
        "post_run_id": post["run_id"],
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "thresholds": thresholds,
        "checks": checks,
        "equivalence_mismatches": mismatches,
        "http": {
            "pre_offered_rps": pre_http.get("offered_rps"),
            "post_offered_rps": post_http.get("offered_rps"),
            "offered_rps_change": offered_rps_change,
            "pre_dropped_iterations": pre_http.get("dropped_iterations", 0),
            "post_dropped_iterations": post_http.get("dropped_iterations", 0),
            "pre_system_error_rate": pre_http.get("system_error_rate"),
            "post_system_error_rate": post_http.get("system_error_rate"),
            "pre_p95_ms": pre_http["latency_ms"].get("p95"),
            "post_p95_ms": post_http["latency_ms"].get("p95"),
            "p95_change": p95_change,
            "pre_p99_ms": pre_http["latency_ms"].get("p99"),
            "post_p99_ms": post_http["latency_ms"].get("p99"),
            "p99_change": p99_change,
            "pre_successful_rps": pre_http.get("successful_rps"),
            "post_successful_rps": post_http.get("successful_rps"),
            "successful_throughput_ratio": throughput_ratio,
        },
        "resource_capacity": {
            "cpu_cores_before": pre_cpu,
            "cpu_cores_after": post_cpu,
            "cpu_reduction": reduction(post_cpu, pre_cpu),
            "memory_bytes_before": pre_memory,
            "memory_bytes_after": post_memory,
            "memory_reduction": reduction(post_memory, pre_memory),
        },
        "post_stability": post_stability,
        "workloads": workloads,
    }


def estimate_cost(result: dict[str, Any], duration_hours: float, cpu_price: float | None, memory_price: float | None) -> None:
    if cpu_price is None or memory_price is None:
        result["request_cost_estimate"] = {
            "status": "not_calculated",
            "reason": "CPU and memory unit prices were not supplied",
        }
        return
    capacity = result["resource_capacity"]
    if any(capacity[key] is None for key in ("cpu_cores_before", "cpu_cores_after", "memory_bytes_before", "memory_bytes_after")):
        result["request_cost_estimate"] = {"status": "not_calculated", "reason": "Required request or replica metrics are missing"}
        return
    gib = 1024 ** 3
    before = (
        capacity["cpu_cores_before"] * cpu_price
        + capacity["memory_bytes_before"] / gib * memory_price
    ) * duration_hours
    after = (
        capacity["cpu_cores_after"] * cpu_price
        + capacity["memory_bytes_after"] / gib * memory_price
    ) * duration_hours
    result["request_cost_estimate"] = {
        "status": "estimated_allocation_cost",
        "currency": "USD",
        "cpu_core_hour_price": cpu_price,
        "memory_gib_hour_price": memory_price,
        "before": before,
        "after": after,
        "reduction": reduction(after, before),
        "disclaimer": "Request-based allocation estimate; not an AWS bill.",
    }


def markdown(result: dict[str, Any]) -> str:
    http = result["http"]
    resources = result["resource_capacity"]
    lines = [
        f"# Bank of Anthos KRR PRE/POST 결과: {result['verdict']}",
        "",
        f"- PRE: {result['pre_run_id']}",
        f"- POST: {result['post_run_id']}",
        f"- 입력 동등성: {'PASS' if result['checks']['equivalent_inputs'] else 'FAIL'}",
        f"- p95 변화: {fmt_percent(http['p95_change'])}",
        f"- p99 변화: {fmt_percent(http['p99_change'])}",
        f"- 성공 throughput 비율: {fmt_percent(http['successful_throughput_ratio'])}",
        f"- CPU request capacity 절감: {fmt_percent(resources['cpu_reduction'])}",
        f"- Memory request capacity 절감: {fmt_percent(resources['memory_reduction'])}",
        "",
    ]
    if result["equivalence_mismatches"]:
        lines += ["## PRE/POST 불일치", "", *[f"- {item}" for item in result["equivalence_mismatches"]], ""]
    lines += [
        "## 컨테이너별 결과",
        "",
        "| 대상 | CPU Request 전→후 | Memory MiB 전→후 | Throttle avg/p95 | OOM | Restart | 판정 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for identifier, item in result["workloads"].items():
        before_mem = item["memory_request_before_bytes"]
        after_mem = item["memory_request_after_bytes"]
        lines.append(
            f"| {identifier} | {fmt_number(item['cpu_request_before'])}→{fmt_number(item['cpu_request_after'])} | "
            f"{fmt_number(before_mem / 1024 ** 2 if before_mem is not None else None, 1)}→"
            f"{fmt_number(after_mem / 1024 ** 2 if after_mem is not None else None, 1)} | "
            f"{fmt_percent(item['post_cpu_throttling_avg'])}/{fmt_percent(item['post_cpu_throttling_p95'])} | "
            f"{fmt_number(item['post_oom'], 0)} | {fmt_number(item['post_restarts'], 0)} | {item['verdict']} |"
        )
    lines += ["", "## 판정 항목", ""]
    lines += [f"- {'PASS' if passed else 'FAIL'}: {name}" for name, passed in result["checks"].items()]
    return "\n".join(lines) + "\n"


def write_csv(path: Path, result: dict[str, Any]) -> None:
    fields = ["identifier", "cpu_request_before", "cpu_request_after", "cpu_request_reduction",
              "memory_request_before_bytes", "memory_request_after_bytes", "memory_request_reduction",
              "post_cpu_throttling_avg", "post_cpu_throttling_p95", "post_oom", "post_restarts", "verdict"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for identifier, values in result["workloads"].items():
            writer.writerow({"identifier": identifier, **values})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", type=Path, required=True)
    parser.add_argument("--post", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--cpu-core-hour-price", type=float)
    parser.add_argument("--memory-gib-hour-price", type=float)
    args = parser.parse_args()

    pre = load(args.pre)
    post = load(args.post)
    if pre.get("phase") != "pre" or post.get("phase") != "post":
        parser.error("input phases must be pre and post")
    thresholds = {**DEFAULT_THRESHOLDS, **load(args.thresholds)}
    result = compare(pre, post, thresholds)
    estimate_cost(
        result,
        float(pre["duration_seconds"]) / 3600,
        args.cpu_core_hour_price,
        args.memory_gib_hour_price,
    )

    for path in (args.json_output, args.markdown_output, args.csv_output):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown(result), encoding="utf-8")
    if args.csv_output:
        write_csv(args.csv_output, result)
    print(result["verdict"])
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
