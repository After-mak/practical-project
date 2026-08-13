import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("collector", ROOT / "k6" / "collect_bank_krr_run.py")
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collector)


def test_percentile_and_stats_do_not_invent_empty_data():
    assert collector.stats([]) == {"avg": None, "p95": None, "max": None}
    values = collector.stats([1, 2, 3, 4, 5])
    assert values["avg"] == 3
    assert values["p95"] == 4.8
    assert values["max"] == 5


def test_k6_summary_separates_failure_classes_and_dropped_iterations(tmp_path):
    summary = {
        "schema_version": "1.0",
        "run_id": "run-pre",
        "phase": "pre",
        "scenario": "boa",
        "metrics": {
            "boa_offered_requests": {"values": {"count": 100, "rate": 10}},
            "boa_successful_requests": {"values": {"count": 97, "rate": 9.7}},
            "boa_system_failures": {"values": {"count": 1}},
            "boa_business_failures": {"values": {"count": 2}},
            "boa_intentional_4xx": {"values": {"count": 3}},
            "boa_flow_success": {"values": {"rate": 0.97}},
            "boa_e2e_latency_ms": {
                "values": {"med": 50, "p(95)": 100, "p(99)": 150, "avg": 60, "max": 200}
            },
            "dropped_iterations": {"values": {"count": 4}},
        },
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    parsed = collector.load_k6_summary(path)

    assert parsed["system_error_rate"] == 0.01
    assert parsed["business_failure_rate"] == 0.02
    assert parsed["intentional_4xx"] == 3
    assert parsed["dropped_iterations"] == 4
    assert parsed["latency_ms"]["p95"] == 100


def test_collect_workload_includes_limits_and_uses_instant_window_counters():
    class Prom:
        start = collector.utc("2026-08-13T00:00:00Z")
        end = collector.utc("2026-08-13T01:00:00Z")
        range_queries = []
        instant_queries = []

        def range_stats(self, query):
            self.range_queries.append(query)
            return {"avg": 1.0, "p95": 1.0, "max": 1.0}

        def instant_value(self, query):
            self.instant_queries.append(query)
            return 0.0

    prom = Prom()
    result = collector.collect_workload(prom, "backend", "userservice", "worker")
    assert result["cpu_limit_cores_per_replica"]["avg"] == 1.0
    assert result["memory_limit_bytes_per_replica"]["avg"] == 1.0
    assert len(prom.instant_queries) == 2
    assert all("[3600s]" in query for query in prom.instant_queries)

def test_krr_duration_parser_is_explicit():
    assert collector.parse_duration_seconds("24h") == 86400
    assert collector.parse_duration_seconds("7d") == 604800
    with pytest.raises(Exception):
        collector.parse_duration_seconds("24")
