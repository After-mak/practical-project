from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from app import ForecastRuntime, create_app
from chronos_prometheus import ForecastResult, ForecastSettings


def make_settings(mode="active", **overrides):
    values = {
        "prometheus_url": "http://thanos-query:9090",
        "target_deployment": "sample-worker",
        "target_namespace": "sample-fastapi",
        "pod_pattern": "sample-worker-.*",
        "container_name": "worker",
        "mode": mode,
        "forecast_interval_seconds": 60,
        "forecast_ttl_seconds": 120,
    }
    values.update(overrides)
    return ForecastSettings(**values)


def make_result(timestamp=None, replicas=3):
    generated = timestamp or datetime.now(timezone.utc)
    return ForecastResult(
        timestamp=generated.isoformat(),
        forecast_start_time=generated.isoformat(),
        forecast_end_time=(generated + timedelta(minutes=12)).isoformat(),
        namespace="sample-fastapi",
        deployment="sample-worker",
        predicted_cpu_usage=1.2,
        predicted_max_cpu_pct=240.0,
        scale_out_needed=True,
        current_replicas=1,
        predicted_replicas=replicas,
        source_points=120,
    )


def make_client(mode="active", forecast=None):
    settings = make_settings(mode)
    runtime = ForecastRuntime(
        settings,
        forecast=forecast or (lambda: make_result()),
        registry=CollectorRegistry(),
    )
    app = create_app(settings, runtime, start_background=False)
    return TestClient(app), runtime


def test_active_mode_exposes_keda_signal_and_existing_finops_api_contract():
    client, runtime = make_client()
    runtime.run_once()

    response = client.get("/predict/sample-fastapi/sample-worker")
    metrics = client.get("/metrics").text

    assert response.status_code == 200
    assert response.json()["model_id"] == "amazon/chronos-2"
    assert response.json()["predicted_max_cpu_pct"] == 240.0
    assert response.json()["predicted_replicas"] == 3
    assert (
        'chronos_scaling_replicas{deployment="sample-worker",namespace="sample-fastapi"} 3.0'
        in metrics
    )
    assert (
        'chronos_forecast_valid{deployment="sample-worker",namespace="sample-fastapi"} 1.0'
        in metrics
    )
    assert 'chronos_model_info{model_id="amazon/chronos-2"} 1.0' in metrics


def test_shadow_mode_records_prediction_without_scaling_signal():
    client, runtime = make_client(mode="shadow")
    runtime.run_once()

    metrics = client.get("/metrics").text

    assert "chronos_predicted_replicas" in metrics
    assert (
        'chronos_scaling_replicas{deployment="sample-worker",namespace="sample-fastapi"} 0.0'
        in metrics
    )
    assert client.get("/health/ready").status_code == 200


def test_disabled_mode_is_healthy_but_does_not_produce_prediction():
    client, runtime = make_client(mode="disabled")
    runtime.run_once()

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["model_id"] == "amazon/chronos-2"
    assert client.get("/health/ready").json()["mode"] == "disabled"
    assert client.get("/predict/sample-fastapi/sample-worker").status_code == 503
    assert "chronos_scaling_replicas" in client.get("/metrics").text


def test_expired_forecast_clears_active_scaling_signal():
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    client, runtime = make_client(forecast=lambda: make_result(old))
    runtime.run_once()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert (
        'chronos_scaling_replicas{deployment="sample-worker",namespace="sample-fastapi"} 0.0'
        in response.text
    )
    assert client.get("/health/ready").status_code == 503


def test_forecast_error_increments_counter_and_queue_fallback_signal_stays_zero():
    def fail():
        raise RuntimeError("thanos unavailable")

    client, runtime = make_client(forecast=fail)
    runtime.run_once()
    metrics = client.get("/metrics").text

    assert (
        'chronos_forecast_errors_total{deployment="sample-worker",namespace="sample-fastapi"} 1.0'
        in metrics
    )
    assert (
        'chronos_scaling_replicas{deployment="sample-worker",namespace="sample-fastapi"} 0.0'
        in metrics
    )
    assert client.get("/health/ready").status_code == 503


def test_unknown_target_is_not_silently_predicted():
    client, runtime = make_client()
    runtime.run_once()

    assert client.get("/predict/default/other").status_code == 404


def test_multi_target_runtime_serves_independent_forecasts_per_workload():
    primary_settings = make_settings(
        target_namespace="frontend", target_deployment="mak-app-rollout"
    )
    extra_settings = make_settings(
        target_namespace="backend", target_deployment="userservice"
    )

    runtime = ForecastRuntime(
        primary_settings,
        forecast=lambda: make_result(),
        registry=CollectorRegistry(),
        extra_targets=[extra_settings],
    )
    # backend/userservice 대상의 예측 함수만 별도 값으로 교체합니다.
    runtime._forecast_fns[("backend", "userservice")] = lambda: ForecastResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        forecast_start_time=datetime.now(timezone.utc).isoformat(),
        forecast_end_time=(
            datetime.now(timezone.utc) + timedelta(minutes=12)
        ).isoformat(),
        namespace="backend",
        deployment="userservice",
        predicted_cpu_usage=0.05,
        predicted_max_cpu_pct=5.0,
        scale_out_needed=False,
        current_replicas=1,
        predicted_replicas=1,
        source_points=120,
    )

    app = create_app(primary_settings, runtime, start_background=False)
    client = TestClient(app)
    runtime.run_once()

    primary_resp = client.get("/predict/frontend/mak-app-rollout")
    backend_resp = client.get("/predict/backend/userservice")
    unknown_resp = client.get("/predict/backend/contacts")

    assert primary_resp.status_code == 200
    assert primary_resp.json()["predicted_max_cpu_pct"] == 240.0
    assert backend_resp.status_code == 200
    assert backend_resp.json()["predicted_max_cpu_pct"] == 5.0
    # 서로 다른 워크로드에 동일한 예측값이 브로드캐스트되지 않아야 합니다.
    assert primary_resp.json()["predicted_max_cpu_pct"] != backend_resp.json()["predicted_max_cpu_pct"]
    assert unknown_resp.status_code == 404
