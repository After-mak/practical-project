import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-bank-krr-test.sh"
MAKEFILE = ROOT / "Makefile"


def config(phase: str) -> dict[str, str]:
    result = subprocess.run(
        ["bash", str(RUNNER), "config", phase],
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_runner_has_expected_safe_default_durations():
    smoke = config("smoke")
    assert smoke["profile"] == "smoke"
    assert smoke["time_scale"] == "1"
    assert smoke["cycles"] == "1"
    assert smoke["expected_duration_seconds"] == "1800"

    pre = config("pre")
    assert pre["profile"] == "long"
    assert pre["time_scale"] == "0.75"
    assert pre["cycles"] == "3"
    assert pre["expected_duration_seconds"] == "10800"
    assert config("post") == {**pre, "phase": "post"}
    assert pre["scale_in_guard"] == "1"
    assert pre["warm_replicas"] == "6"


def test_runner_rejects_unknown_phase():
    result = subprocess.run(
        ["bash", str(RUNNER), "config", "unknown"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "phase" in result.stderr


def test_makefile_exposes_all_bank_commands():
    source = MAKEFILE.read_text()
    for target in (
        "bank-help:",
        "bank-smoke:",
        "bank-pre:",
        "bank-post:",
        "bank-status:",
        "bank-recheck:",
        "bank-stop:",
        "bank-compare:",
    ):
        assert target in source


def test_runner_guards_scale_in_and_restores_original_state():
    source = RUNNER.read_text()
    assert "autoscaling.keda.sh/paused-scale-in=true" in source
    assert "autoscaling.keda.sh/paused-scale-in-" in source
    assert '"autoscaling.keda.sh/paused-scale-in=$previous"' in source
    assert "trap cleanup_runtime EXIT" in source
    assert "enable_scale_in_guard" in source
    assert "restore_scale_in_guard" in source


def test_runner_counts_the_actual_frontend_rollout_pods():
    source = RUNNER.read_text()
    assert "get pods -l app=frontend" in source
    assert "wait --for=condition=Ready pod --all" not in source
    assert "-l application=bank-of-anthos" in source
    assert "deployment/transactionhistory" in source
