import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from finops.app.clients import KrrClient


def row(workload: str, container: str, cpu: float, memory: float) -> dict:
    return {
        "object": {
            "namespace": "backend",
            "name": workload,
            "container": container,
            "kind": "Deployment",
            "allocations": {
                "requests": {"cpu": cpu, "memory": memory},
                "limits": {"cpu": 0.5, "memory": 512 * 1024 * 1024},
            },
        },
        "recommended": {"requests": {"cpu": cpu / 2, "memory": memory / 2}},
    }


def test_parser_keeps_app_and_worker_separate():
    client = KrrClient("http://prometheus", "24h")
    parsed = client._parse_krr_output(
        [
            row("userservice", "userservice", 0.2, 256 * 1024 * 1024),
            row("userservice", "worker", 0.25, 256 * 1024 * 1024),
        ],
        "backend",
    )

    assert set(parsed) == {
        "backend/userservice/userservice",
        "backend/userservice/worker",
    }
    assert parsed["backend/userservice/userservice"]["krr_recommended"]["cpu"] == "100m"
    assert parsed["backend/userservice/worker"]["krr_recommended"]["cpu"] == "125m"


@pytest.mark.asyncio
async def test_history_duration_is_passed_to_krr(monkeypatch):
    captured = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"[]", b""

    async def fake_process(*args, **kwargs):
        captured.extend(args)
        return Process()

    monkeypatch.setattr("finops.app.clients.asyncio.create_subprocess_exec", fake_process)
    client = KrrClient("http://prometheus", "24h")
    assert await client._scan_namespace("backend") == {}
    assert captured[captured.index("--history_duration") + 1] == "24"
    assert captured[captured.index("--cpu_percentile") + 1] == "95"


@pytest.mark.asyncio
async def test_ambiguous_workload_requires_container(monkeypatch):
    client = KrrClient("http://prometheus", "24h")
    scan = {
        "backend/userservice/userservice": {
            "namespace": "backend", "workload": "userservice", "container": "userservice"
        },
        "backend/userservice/worker": {
            "namespace": "backend", "workload": "userservice", "container": "worker"
        },
    }

    async def fake_scan(*_args):
        return scan

    monkeypatch.setattr(client, "_scan_namespace", fake_scan)
    assert await client.get_recommendation("userservice", "backend") is None
    result = await client.get_recommendation("userservice", "backend", "worker")
    assert result["container"] == "worker"


def test_bank_workload_map_has_all_container_paths():
    mapping = json.loads((ROOT / "finops" / "bank-workload-map.json").read_text())
    assert len(mapping["workloads"]) == 11
    assert mapping["workloads"]["frontend/mak-app-rollout/mak-container"]["kind"] == "Rollout"
    assert all(item["requests_path"].endswith(".requests") for item in mapping["workloads"].values())


@pytest.mark.asyncio
async def test_day_history_is_normalized_to_krr_hours(monkeypatch):
    captured = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"[]", b""

    async def fake_process(*args, **kwargs):
        captured.extend(args)
        return Process()

    monkeypatch.setattr("finops.app.clients.asyncio.create_subprocess_exec", fake_process)
    await KrrClient("http://prometheus")._scan_namespace("backend", "7d")
    assert captured[captured.index("--history_duration") + 1] == "168"

def test_official_krr_json_shape_preserves_current_quantities():
    payload = {
        "scans": [{
            "object": {
                "namespace": "backend", "name": "userservice",
                "container": "userservice", "kind": "Deployment",
                "allocations": {
                    "requests": {"cpu": "50m", "memory": "2048Mi"},
                    "limits": {"cpu": "500m", "memory": "3Gi"},
                },
            },
            "recommended": {
                "requests": {
                    "cpu": {"value": 0.025},
                    "memory": {"value": "?"},
                }
            },
        }]
    }
    result = KrrClient()._parse_krr_output(payload, "backend")["backend/userservice/userservice"]
    assert result["current"] == {"cpu": "50m", "memory": "2048Mi"}
    assert result["current_limits"] == {"cpu": "500m", "memory": "3Gi"}
    assert result["krr_recommended"]["cpu"] == "25m"
    assert result["krr_recommended"]["memory"] is None


def test_finops_chart_grants_rollout_read_only_access():
    chart = Path(__file__).resolve().parents[1] / "charts" / "finops"
    output = subprocess.run(
        ["helm", "template", "finops", str(chart), "--namespace", "finops"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    expected_rule = """  - apiGroups: ["argoproj.io"]
    resources:
      - rollouts
      - rollouts/scale
    verbs: ["get", "list", "watch"]"""
    assert expected_rule in output
    assert 'verbs: ["create"' not in output
    assert 'verbs: ["delete"' not in output
