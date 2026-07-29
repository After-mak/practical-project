from datetime import datetime, timezone

import pytest

from chronos_prometheus import (
    ForecastEngine,
    ForecastSettings,
    build_cpu_query,
    fetch_cpu_series,
    legacy_cli_settings_from_environment,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


class FixedModel:
    def __init__(self, predicted_max):
        self.predicted_max = predicted_max
        self.values = None

    def predict_max(self, values, prediction_length):
        self.values = list(values)
        return self.predicted_max


def settings(**overrides):
    values = {
        "prometheus_url": "http://thanos-query:9090",
        "target_deployment": "sample-worker",
        "target_namespace": "sample-fastapi",
        "pod_pattern": "sample-worker-.*",
        "container_name": "worker",
        "mode": "active",
        "prediction_length": 3,
        "step_seconds": 60,
        "min_replicas": 1,
        "max_replicas": 3,
    }
    values.update(overrides)
    return ForecastSettings(**values)


def test_cpu_query_aggregates_the_whole_deployment():
    query = build_cpu_query(settings())

    assert query.startswith("sum(rate(")
    assert 'namespace="sample-fastapi"' in query
    assert 'pod=~"sample-worker-.*"' in query
    assert 'container="worker"' in query
    assert "by (pod)" not in query


def test_cpu_query_can_keep_legacy_container_agnostic_behavior():
    query = build_cpu_query(settings(container_name=""))

    assert 'container="' not in query
    assert 'container!="POD"' in query


def test_legacy_cli_defaults_are_preserved(monkeypatch):
    for name in (
        "PROM_URL",
        "CHRONOS_TARGET_DEPLOYMENT",
        "CHRONOS_TARGET_NAMESPACE",
        "CHRONOS_POD_PATTERN",
        "CHRONOS_CONTAINER",
        "FORECAST_FILE",
    ):
        monkeypatch.delenv(name, raising=False)

    legacy = legacy_cli_settings_from_environment()

    assert legacy.prometheus_url == "http://localhost:9090"
    assert legacy.target_deployment == "test-overprovisioned"
    assert legacy.target_namespace == "default"
    assert legacy.pod_pattern == "test\\-overprovisioned.*"
    assert legacy.container_name == ""
    assert legacy.forecast_output == "~/k8s-manifest/forecast_result.json"


def test_fetch_cpu_series_combines_defensive_multiple_results():
    session = FakeSession(
        {
            "status": "success",
            "data": {
                "result": [
                    {"values": [[100, "0.1"], [160, "0.2"], [220, "0.3"]]},
                    {"values": [[100, "0.4"], [160, "0.5"], [220, "0.6"]]},
                ]
            },
        }
    )

    values = fetch_cpu_series(
        settings(),
        session=session,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert values == pytest.approx([0.5, 0.7, 0.9])
    assert session.calls[0][0] == "http://thanos-query:9090/api/v1/query_range"
    assert session.calls[0][1]["params"]["step"] == "60s"


def test_forecast_converts_cpu_to_clamped_replica_signal():
    session = FakeSession(
        {
            "status": "success",
            "data": {
                "result": [
                    {"values": [[100, "0.1"], [160, "0.2"], [220, "0.3"]]}
                ]
            },
        }
    )
    model = FixedModel(2.2)
    engine = ForecastEngine(settings(), model, session=session)

    result = engine.forecast(now=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert result.predicted_cpu_usage == 2.2
    assert result.predicted_replicas == 3
    assert result.scale_out_needed is True
    assert result.predicted_max_cpu_pct == 440.0
    assert result.source_points == 3


def test_not_enough_prometheus_points_fails_fast():
    session = FakeSession(
        {
            "status": "success",
            "data": {"result": [{"values": [[100, "0.1"], [160, "0.2"]]}]},
        }
    )

    with pytest.raises(RuntimeError, match="Not enough CPU data points"):
        fetch_cpu_series(settings(), session=session)


def test_fake_replicas_bypass_prometheus_and_model_for_keda_contract_test():
    model = FixedModel(99)
    engine = ForecastEngine(settings(fake_replicas=3), model, session=None)

    result = engine.forecast(now=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert result.predicted_cpu_usage == 1.5
    assert result.predicted_replicas == 3
    assert result.source_points == 0
    assert model.values is None


def test_legacy_cli_keeps_current_replicas_when_scale_out_is_not_needed():
    session = FakeSession(
        {
            "status": "success",
            "data": {
                "result": [
                    {"values": [[100, "0.1"], [160, "0.2"], [220, "0.3"]]}
                ]
            },
        }
    )
    engine = ForecastEngine(
        settings(),
        FixedModel(0.2),
        session=session,
        current_replicas_provider=lambda: 2,
        preserve_current_when_below_threshold=True,
    )

    result = engine.forecast(now=datetime(2026, 7, 29, tzinfo=timezone.utc))

    assert result.current_replicas == 2
    assert result.predicted_replicas == 2
    assert result.scale_out_needed is False
    assert result.to_dict()["pod"] == "sample-worker"
