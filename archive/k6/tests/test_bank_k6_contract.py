import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "k6" / "bank-of-anthos-long-run.js"
K6 = shutil.which("k6")
BASE_ARGS = [
    "-e", "BASE_URL=http://example.test",
    "-e", "RUN_ID=contract-test",
    "-e", "SCENARIO_NAME=boa-contract",
    "-e", "TEST_USERNAME=test-user",
    "-e", "TEST_PASSWORD=redacted",
]


def seconds(value: str) -> int:
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", value):
        total += int(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def inspect(*environment: str) -> dict:
    if not K6:
        pytest.skip("k6 is not installed")
    args = [K6, "inspect", *BASE_ARGS]
    for item in environment:
        args.extend(["-e", item])
    args.extend(["--execution-requirements", str(SCRIPT)])
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def scenario_end_seconds(payload: dict) -> int:
    def duration(item: dict) -> int:
        if "duration" in item:
            return seconds(item["duration"])
        return sum(seconds(stage["duration"]) for stage in item["stages"])

    return max(
        seconds(item["startTime"]) + duration(item)
        for item in payload["scenarios"].values()
    )


def test_smoke_profile_is_exactly_30_minutes_and_has_required_phases():
    payload = inspect("PHASE=smoke", "PROFILE=smoke")
    assert scenario_end_seconds(payload) == 30 * 60
    assert {item["tags"]["traffic_phase"] for item in payload["scenarios"].values()} == {
        "low", "normal", "peak", "spike", "recovery"
    }
    assert "p(99)" in payload["summaryTrendStats"]


def test_long_profile_18_cycles_is_exactly_24_hours():
    payload = inspect("PHASE=pre", "PROFILE=long", "CYCLES=18")
    assert len(payload["scenarios"]) == 18 * 7
    assert scenario_end_seconds(payload) == 24 * 60 * 60
    assert {item["tags"]["traffic_phase"] for item in payload["scenarios"].values()} == {
        "low", "ramp_up", "normal", "peak", "spike", "ramp_down", "recovery"
    }


def test_missing_required_environment_and_payment_recipient_fail_clearly():
    if not K6:
        pytest.skip("k6 is not installed")
    missing = subprocess.run(
        [K6, "inspect", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert missing.returncode != 0
    assert "missing required environment variables" in missing.stderr

    payment = subprocess.run(
        [K6, "inspect", *BASE_ARGS, "-e", "PHASE=pre", "-e", "PAYMENT_PERCENT=1", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert payment.returncode != 0
    assert "TEST_RECIPIENT_ACCOUNT is required" in payment.stderr
