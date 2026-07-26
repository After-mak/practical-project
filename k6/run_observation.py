#!/usr/bin/env python3
"""k6 실행 시간과 Kubernetes 전후 상태를 KRR 전달용 JSON으로 기록합니다."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
K6_DIR = ROOT / "k6"
SCENARIOS = {
    "baseline": "baseline-test.js",
    "overallocated": "overallocated-test.js",
    "idle": "idle-test.js",
    "spike": "spike-test.js",
    "queue": "queue-scale-test.js",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    """명령의 출력과 종료 코드를 기록하고 조회 실패는 전체 실행을 중단하지 않습니다."""

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except FileNotFoundError as exc:
        return {"command": command, "returncode": 127, "stderr": str(exc), "stdout": ""}


def kubernetes_snapshot(namespace: str, deployment: str) -> dict[str, Any]:
    return {
        "deployment": run(
            [
                "kubectl",
                "get",
                "deployment",
                deployment,
                "-n",
                namespace,
                "-o",
                "json",
            ]
        ),
        "pods": run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                f"app.kubernetes.io/name=sample-fastapi",
                "-o",
                "wide",
            ]
        ),
        "top": run(["kubectl", "top", "pods", "-n", namespace]),
        "hpa": run(["kubectl", "get", "hpa", "-n", namespace, "-o", "wide"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--namespace", default="sample-fastapi")
    parser.add_argument("--deployment")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", default="k6/results")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    args = parser.parse_args()

    deployment = args.deployment or (
        "sample-worker" if args.scenario == "queue" else f"sample-fastapi-{args.scenario}"
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_file = output_dir / f"{args.scenario}-{timestamp}-k6.json"
    report_file = output_dir / f"{args.scenario}-{timestamp}-observation.json"

    environment = os.environ.copy()
    environment["BASE_URL"] = args.base_url
    for item in args.env:
        name, separator, value = item.partition("=")
        if not separator or not name:
            parser.error(f"invalid --env value: {item!r}")
        environment[name] = value

    report: dict[str, Any] = {
        "scenario": args.scenario,
        "namespace": args.namespace,
        "deployment": deployment,
        "base_url": args.base_url,
        "started_at": utc_now(),
        "before": kubernetes_snapshot(args.namespace, deployment),
        "promql": {
            "cpu": (
                f'rate(container_cpu_usage_seconds_total{{namespace="{args.namespace}",'
                f'pod=~"{deployment}-.*",container!="POD"}}[5m])'
            ),
            "memory": (
                f'container_memory_working_set_bytes{{namespace="{args.namespace}",'
                f'pod=~"{deployment}-.*",container!="POD"}}'
            ),
            "queue": 'max(sample_queue_length{namespace="sample-fastapi"})',
            "replicas": (
                f'kube_deployment_status_replicas{{namespace="{args.namespace}",'
                f'deployment="{deployment}"}}'
            ),
        },
    }

    k6_command = [
        "k6",
        "run",
        "--summary-export",
        str(summary_file),
        str(K6_DIR / SCENARIOS[args.scenario]),
    ]
    report["k6"] = run(k6_command, env=environment)
    report["ended_at"] = utc_now()
    report["after"] = kubernetes_snapshot(args.namespace, deployment)
    report["summary_file"] = str(summary_file)
    report_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report_file)
    return int(report["k6"]["returncode"])


if __name__ == "__main__":
    raise SystemExit(main())
