import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "k6" / "compare_bank_krr_runs.py"


def run(phase: str, cpu: float, memory: float, p95: float = 100, p99: float = 150,
        rps: float = 10, error: float = 0, throttle: float = 0.01) -> dict:
    identifiers = [
        "frontend/mak-app-rollout/mak-container",
        "backend/userservice/userservice", "backend/userservice/worker",
        "backend/contacts/contacts", "backend/contacts/worker",
        "backend/balancereader/balancereader", "backend/balancereader/worker",
        "backend/ledgerwriter/ledgerwriter", "backend/ledgerwriter/worker",
        "backend/transactionhistory/transactionhistory", "backend/transactionhistory/worker",
    ]
    return {
        "run_id": f"run-{phase}",
        "phase": phase,
        "duration_seconds": 3600,
        "application_commit": "app-commit",
        "gitops_commit": f"gitops-{phase}",
        "scenario": "boa-long-cycle-v1",
        "scenario_sha256": "same-hash",
        "equivalence": {
            "application_image": "bank@sha256:abc",
            "loadgen_image": "k6@sha256:def",
            "scenario_config": {"low": 1, "normal": 10, "peak": 25, "spike": 40},
            "db_state_id": "snapshot-001",
            "autoscaling": {"max": 5},
            "node_pool": {"name": "default"},
        },
        "http": {
            "system_error_rate": error,
            "business_failure_rate": 0,
            "offered_rps": 10,
            "dropped_iterations": 0,
            "successful_rps": rps,
            "latency_ms": {"p95": p95, "p99": p99},
        },
        "workloads": {
            identifier: {
                "cpu_request_cores_per_replica": {"avg": cpu},
                "memory_request_bytes_per_replica": {"avg": memory},
                "cpu_limit_cores_per_replica": {"avg": 1.0},
                "cpu_throttling_ratio": {"avg": throttle, "p95": throttle},
                "oom_killed_pods": 0,
                "restart_increase": 0,
                "replicas": {"avg": 2, "max": 2},
            }
            for identifier in identifiers
        },
    }


def invoke(tmp_path: Path, pre: dict, post: dict) -> tuple[subprocess.CompletedProcess, dict]:
    pre_path = tmp_path / "pre.json"
    post_path = tmp_path / "post.json"
    output = tmp_path / "result.json"
    pre_path.write_text(json.dumps(pre))
    post_path.write_text(json.dumps(post))
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--pre", str(pre_path), "--post", str(post_path),
            "--thresholds", str(ROOT / "k6" / "bank-krr-success-criteria.json"),
            "--json-output", str(output), "--markdown-output", str(tmp_path / "result.md"),
            "--csv-output", str(tmp_path / "result.csv"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result, json.loads(output.read_text())


def test_equivalent_safe_resource_reduction_passes(tmp_path):
    pre = run("pre", 0.2, 256 * 1024 ** 2)
    post = run("post", 0.15, 192 * 1024 ** 2, p95=105, p99=160, rps=9.8)
    process, result = invoke(tmp_path, pre, post)

    assert process.returncode == 0
    assert result["verdict"] == "PASS"
    assert result["checks"]["resource_reduction"]
    assert round(result["resource_capacity"]["cpu_reduction"], 2) == 0.25


def test_input_mismatch_fails_even_when_performance_is_good(tmp_path):
    pre = run("pre", 0.2, 256 * 1024 ** 2)
    post = run("post", 0.15, 192 * 1024 ** 2)
    post["equivalence"]["db_state_id"] = "different-snapshot"
    process, result = invoke(tmp_path, pre, post)

    assert process.returncode == 2
    assert result["verdict"] == "FAIL"
    assert "equivalence.db_state_id" in result["equivalence_mismatches"]


def test_oom_or_latency_regression_fails(tmp_path):
    pre = run("pre", 0.2, 256 * 1024 ** 2)
    post = run("post", 0.15, 192 * 1024 ** 2, p95=120)
    post["workloads"]["backend/userservice/userservice"]["oom_killed_pods"] = 1
    process, result = invoke(tmp_path, pre, post)

    assert process.returncode == 2
    assert not result["checks"]["p95_latency"]
    assert not result["checks"]["oom"]


def test_missing_metric_fails_closed(tmp_path):
    pre = run("pre", 0.2, 256 * 1024 ** 2)
    post = run("post", 0.15, 192 * 1024 ** 2)
    post["workloads"]["backend/userservice/worker"]["cpu_throttling_ratio"]["p95"] = None
    process, result = invoke(tmp_path, pre, post)
    assert process.returncode == 2
    assert not result["checks"]["complete_metrics"]
    assert result["workloads"]["backend/userservice/worker"]["verdict"] == "FAIL"

def test_unlimited_container_allows_missing_throttling_metrics(tmp_path):
    pre = run("pre", 0.2, 256 * 1024 ** 2)
    post = run("post", 0.15, 192 * 1024 ** 2)
    identifier = "backend/userservice/userservice"
    for payload in (pre, post):
        payload["workloads"][identifier]["cpu_limit_cores_per_replica"]["avg"] = None
        payload["workloads"][identifier]["cpu_throttling_ratio"] = {
            "avg": None,
            "p95": None,
        }
    process, result = invoke(tmp_path, pre, post)
    assert process.returncode == 0
    assert result["checks"]["complete_metrics"]
    assert result["workloads"][identifier]["verdict"] == "PASS"
