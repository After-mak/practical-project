"""Chronos 예측 API와 KEDA용 Prometheus 메트릭 서버입니다."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from fastapi import FastAPI, HTTPException, Response, status
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from chronos_prometheus import (
    ForecastEngine,
    ForecastResult,
    ForecastSettings,
)


logger = logging.getLogger("chronos-service")


def _parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


@dataclass
class RuntimeState:
    latest: ForecastResult | None = None
    valid: bool = False
    last_error: str | None = None


class ForecastRuntime:
    def __init__(
        self,
        settings: ForecastSettings,
        forecast: Callable[[], ForecastResult] | None = None,
        *,
        registry: CollectorRegistry | None = None,
    ):
        self.settings = settings
        self.forecast = forecast or ForecastEngine(settings).forecast
        self.registry = registry or CollectorRegistry()
        self.state = RuntimeState()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        labels = ("namespace", "deployment")
        metric_kwargs = {"registry": self.registry, "labelnames": labels}
        self.predicted_cpu = Gauge(
            "chronos_predicted_cpu_cores",
            "Maximum predicted deployment CPU demand in cores",
            **metric_kwargs,
        )
        self.predicted_replicas = Gauge(
            "chronos_predicted_replicas",
            "Replica count calculated from the latest forecast",
            **metric_kwargs,
        )
        self.scaling_replicas = Gauge(
            "chronos_scaling_replicas",
            "Replica signal consumed by the KEDA predictive trigger",
            **metric_kwargs,
        )
        self.forecast_timestamp = Gauge(
            "chronos_forecast_timestamp_seconds",
            "Unix timestamp when the latest forecast was generated",
            **metric_kwargs,
        )
        self.forecast_start = Gauge(
            "chronos_forecast_start_time_seconds",
            "Unix timestamp of the forecast window start",
            **metric_kwargs,
        )
        self.forecast_end = Gauge(
            "chronos_forecast_end_time_seconds",
            "Unix timestamp of the forecast window end",
            **metric_kwargs,
        )
        self.forecast_valid = Gauge(
            "chronos_forecast_valid",
            "Whether the latest forecast is valid and fresh",
            **metric_kwargs,
        )
        self.execution_seconds = Gauge(
            "chronos_forecast_execution_seconds",
            "Duration of the latest forecast execution",
            **metric_kwargs,
        )
        self.errors = Counter(
            "chronos_forecast_errors_total",
            "Number of forecast execution errors",
            **metric_kwargs,
        )
        self.mode = Gauge(
            "chronos_mode",
            "Current Chronos mode (disabled, shadow, or active)",
            labelnames=("mode",),
            registry=self.registry,
        )
        for name in ("disabled", "shadow", "active"):
            self.mode.labels(mode=name).set(1 if settings.mode == name else 0)
        self._set_inactive_metrics()

    @property
    def metric_labels(self) -> tuple[str, str]:
        return self.settings.target_namespace, self.settings.target_deployment

    def _set_inactive_metrics(self) -> None:
        labels = self.metric_labels
        self.predicted_cpu.labels(*labels).set(0)
        self.predicted_replicas.labels(*labels).set(self.settings.min_replicas)
        self.scaling_replicas.labels(*labels).set(0)
        self.forecast_timestamp.labels(*labels).set(0)
        self.forecast_start.labels(*labels).set(0)
        self.forecast_end.labels(*labels).set(0)
        self.forecast_valid.labels(*labels).set(0)
        self.execution_seconds.labels(*labels).set(0)

    def run_once(self) -> ForecastResult | None:
        if self.settings.mode == "disabled":
            with self.lock:
                self.state.valid = False
                self.state.last_error = None
                self._set_inactive_metrics()
            return None

        started = time.monotonic()
        labels = self.metric_labels
        try:
            result = self.forecast()
        except Exception as exc:
            logger.exception("Chronos forecast failed")
            with self.lock:
                self.state.valid = False
                self.state.last_error = str(exc)
                self.scaling_replicas.labels(*labels).set(0)
                self.forecast_valid.labels(*labels).set(0)
                self.execution_seconds.labels(*labels).set(
                    time.monotonic() - started
                )
                self.errors.labels(*labels).inc()
            return None

        with self.lock:
            self.state.latest = result
            self.state.valid = True
            self.state.last_error = None
            self.predicted_cpu.labels(*labels).set(result.predicted_cpu_usage)
            self.predicted_replicas.labels(*labels).set(
                result.predicted_replicas
            )
            self.scaling_replicas.labels(*labels).set(
                result.predicted_replicas
                if self.settings.mode == "active"
                else 0
            )
            self.forecast_timestamp.labels(*labels).set(
                _parse_timestamp(result.timestamp)
            )
            self.forecast_start.labels(*labels).set(
                _parse_timestamp(result.forecast_start_time)
            )
            self.forecast_end.labels(*labels).set(
                _parse_timestamp(result.forecast_end_time)
            )
            self.forecast_valid.labels(*labels).set(1)
            self.execution_seconds.labels(*labels).set(
                time.monotonic() - started
            )
        return result

    def refresh_expiry(self, *, now_timestamp: float | None = None) -> bool:
        now = now_timestamp if now_timestamp is not None else time.time()
        labels = self.metric_labels
        with self.lock:
            latest = self.state.latest
            if latest is None:
                self.state.valid = False
            else:
                age = now - _parse_timestamp(latest.timestamp)
                if age > self.settings.forecast_ttl_seconds:
                    self.state.valid = False
                    self.state.last_error = (
                        f"forecast expired after {age:.1f}s "
                        f"(ttl={self.settings.forecast_ttl_seconds}s)"
                    )
            if not self.state.valid:
                self.scaling_replicas.labels(*labels).set(0)
                self.forecast_valid.labels(*labels).set(0)
            return self.state.valid

    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(
            target=self._run_loop, name="chronos-forecast-loop", daemon=True
        )
        self.thread.start()

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            self.run_once()
            self.stop_event.wait(self.settings.forecast_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def prediction_response(self) -> dict:
        self.refresh_expiry()
        with self.lock:
            if not self.state.valid or self.state.latest is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=self.state.last_error or "forecast is not available",
                )
            result = self.state.latest
            return {
                # 기존 FinOps ChronosClient 계약
                "predicted_max_cpu_pct": result.predicted_max_cpu_pct,
                "predicted_max_mem_pct": None,
                "predicted_req_per_sec": None,
                # KEDA·관측용 상세 계약
                "predicted_cpu_cores": result.predicted_cpu_usage,
                "predicted_replicas": result.predicted_replicas,
                "forecast_valid": True,
                "forecast_timestamp": result.timestamp,
                "forecast_start_time": result.forecast_start_time,
                "forecast_end_time": result.forecast_end_time,
                "mode": self.settings.mode,
                "source_points": result.source_points,
            }


def create_app(
    settings: ForecastSettings | None = None,
    runtime: ForecastRuntime | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    configured_settings = settings or ForecastSettings.from_environment()
    configured_runtime = runtime or ForecastRuntime(configured_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_background:
            configured_runtime.start()
        yield
        configured_runtime.stop()

    application = FastAPI(
        title="Chronos Predictive Autoscaling Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.forecast_runtime = configured_runtime

    @application.get("/health/live")
    def live() -> dict:
        return {"status": "alive", "mode": configured_settings.mode}

    @application.get("/health/ready")
    def ready() -> dict:
        if configured_settings.mode == "disabled":
            return {"status": "ready", "mode": "disabled"}
        if not configured_runtime.refresh_expiry():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=configured_runtime.state.last_error
                or "no valid forecast is available",
            )
        return {"status": "ready", "mode": configured_settings.mode}

    @application.get("/predict/{namespace}/{deployment}")
    def predict(namespace: str, deployment: str) -> dict:
        if (
            namespace != configured_settings.target_namespace
            or deployment != configured_settings.target_deployment
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "unsupported forecast target; configured target is "
                    f"{configured_settings.target_namespace}/"
                    f"{configured_settings.target_deployment}"
                ),
            )
        return configured_runtime.prediction_response()

    @application.get("/metrics")
    def metrics() -> Response:
        configured_runtime.refresh_expiry()
        return Response(
            content=generate_latest(configured_runtime.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return application


app = create_app()
