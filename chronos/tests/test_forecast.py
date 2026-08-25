import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from chronos_prometheus import (
    Chronos2Model,
    ForecastEngine,
    ForecastSettings,
    build_cpu_query,
    fetch_cpu_series,
    legacy_cli_settings_from_environment,
    parse_targets_from_environment,
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


class FakePointForecast:
    def __init__(self, maximum):
        self.maximum = maximum

    def max(self):
        return self

    def item(self):
        return self.maximum


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


def test_chronos2_model_uses_official_pipeline_and_median_forecast(monkeypatch):
    calls = {}

    class FakeChronos2Pipeline:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls["load"] = (model_id, kwargs)
            return cls()

        def predict_quantiles(self, inputs, **kwargs):
            calls["predict"] = (inputs, kwargs)
            return [object()], [FakePointForecast(0.75)]

    fake_torch = SimpleNamespace(
        float32="float32",
        tensor=lambda values, dtype: ("tensor", list(values), dtype),
    )
    monkeypatch.setitem(
        sys.modules,
        "chronos",
        SimpleNamespace(Chronos2Pipeline=FakeChronos2Pipeline),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    model = Chronos2Model("amazon/chronos-2")
    predicted_max = model.predict_max([0.1, 0.2, 0.3], 12)

    assert predicted_max == 0.75
    assert calls["load"] == (
        "amazon/chronos-2",
        {"device_map": "cpu", "torch_dtype": "float32"},
    )
    assert calls["predict"][0] == [
        ("tensor", [0.1, 0.2, 0.3], "float32")
    ]
    assert calls["predict"][1] == {
        "prediction_length": 12,
        "quantile_levels": [0.5],
    }


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
    assert legacy.model_id == "amazon/chronos-2"
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


def test_parse_targets_falls_back_to_primary_when_env_unset(monkeypatch):
    monkeypatch.delenv("CHRONOS_TARGETS", raising=False)

    primary = settings()
    targets = parse_targets_from_environment(primary)

    assert targets == [primary]


def test_parse_targets_expands_each_workload_from_json_env(monkeypatch):
    monkeypatch.setenv(
        "CHRONOS_TARGETS",
        (
            '[{"namespace": "frontend", "deployment": "mak-app-rollout", '
            '"pod_pattern": "mak-app-rollout-.*", "container": "mak-container"}, '
            '{"namespace": "backend", "deployment": "userservice", '
            '"container": "userservice"}]'
        ),
    )

    primary = settings(target_namespace="sample-fastapi", target_deployment="sample-worker")
    targets = parse_targets_from_environment(primary)

    assert [(t.target_namespace, t.target_deployment) for t in targets] == [
        ("frontend", "mak-app-rollout"),
        ("backend", "userservice"),
    ]
    assert targets[0].pod_pattern == "mak-app-rollout-.*"
    assert targets[0].container_name == "mak-container"
    # pod_pattern이 없는 항목은 deployment 이름으로 자동 생성됩니다.
    assert targets[1].pod_pattern == "userservice-.*"
    # 나머지 튜닝값은 primary 설정을 그대로 물려받습니다.
    assert targets[1].prometheus_url == primary.prometheus_url
    assert targets[1].mode == primary.mode


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
