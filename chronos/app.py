"""Chronos 예측 API와 KEDA용 Prometheus 메트릭 서버입니다."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from fastapi import FastAPI, HTTPException, Response, status
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from chronos_prometheus import (
    Chronos2Model,
    ForecastEngine,
    ForecastResult,
    ForecastSettings,
    parse_targets_from_environment,
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
        extra_targets: Sequence[ForecastSettings] = (),
    ):
        self.settings = settings
        self.registry = registry or CollectorRegistry()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

        primary_key = (settings.target_namespace, settings.target_deployment)
        self._settings_by_key: dict[tuple[str, str], ForecastSettings] = {
            primary_key: settings
        }
        self._forecast_fns: dict[tuple[str, str], Callable[[], ForecastResult]] = {
            primary_key: forecast or ForecastEngine(settings).forecast
        }
        self._states: dict[tuple[str, str], RuntimeState] = {
            primary_key: RuntimeState()
        }

        if extra_targets:
            # 워크로드별로 매번 모델을 새로 로딩하지 않도록 Chronos2Pipeline을 공유합니다.
            shared_model = Chronos2Model(settings.model_id)
            for target_settings in extra_targets:
                key = (
                    target_settings.target_namespace,
                    target_settings.target_deployment,
                )
                if key in self._settings_by_key:
                    continue
                self._settings_by_key[key] = target_settings
                self._forecast_fns[key] = ForecastEngine(
                    target_settings, model=shared_model
                ).forecast
                self._states[key] = RuntimeState()

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
        self.model_info = Gauge(
            "chronos_model_info",
            "Configured Chronos model",
            labelnames=("model_id",),
            registry=self.registry,
        )
        self.model_info.labels(model_id=settings.model_id).set(1)
        for name in ("disabled", "shadow", "active"):
            self.mode.labels(mode=name).set(1 if settings.mode == name else 0)
        for key in self._settings_by_key:
            self._set_inactive_metrics(key)

    @property
    def target_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._settings_by_key.keys())

    @property
    def metric_labels(self) -> tuple[str, str]:
        """하위 호환용: 주(primary) 대상의 라벨입니다."""
        return self.settings.target_namespace, self.settings.target_deployment

    @property
    def primary_state(self) -> RuntimeState:
        return self._states[self.metric_labels]

    def _set_inactive_metrics(self, key: tuple[str, str]) -> None:
        target_settings = self._settings_by_key[key]
        self.predicted_cpu.labels(*key).set(0)
        self.predicted_replicas.labels(*key).set(target_settings.min_replicas)
        self.scaling_replicas.labels(*key).set(0)
        self.forecast_timestamp.labels(*key).set(0)
        self.forecast_start.labels(*key).set(0)
        self.forecast_end.labels(*key).set(0)
        self.forecast_valid.labels(*key).set(0)
        self.execution_seconds.labels(*key).set(0)

    def run_once(self) -> ForecastResult | None:
        """등록된 모든 대상에 대해 예측을 한 번씩 수행하고, 주 대상의 결과를 반환합니다."""
        primary_result: ForecastResult | None = None
        for key in self.target_keys:
            result = self._run_once_for(key)
            if key == self.metric_labels:
                primary_result = result
        return primary_result

    def _run_once_for(self, key: tuple[str, str]) -> ForecastResult | None:
        target_settings = self._settings_by_key[key]
        if target_settings.mode == "disabled":
            with self.lock:
                self._states[key].valid = False
                self._states[key].last_error = None
                self._set_inactive_metrics(key)
            return None

        started = time.monotonic()
        try:
            result = self._forecast_fns[key]()
        except Exception as exc:
            logger.exception("Chronos forecast failed for %s/%s", *key)
            with self.lock:
                self._states[key].valid = False
                self._states[key].last_error = str(exc)
                self.scaling_replicas.labels(*key).set(0)
                self.forecast_valid.labels(*key).set(0)
                self.execution_seconds.labels(*key).set(
                    time.monotonic() - started
                )
                self.errors.labels(*key).inc()
            return None

        with self.lock:
            state = self._states[key]
            state.latest = result
            state.valid = True
            state.last_error = None
            self.predicted_cpu.labels(*key).set(result.predicted_cpu_usage)
            self.predicted_replicas.labels(*key).set(result.predicted_replicas)
            self.scaling_replicas.labels(*key).set(
                result.predicted_replicas
                if target_settings.mode == "active"
                else 0
            )
            self.forecast_timestamp.labels(*key).set(
                _parse_timestamp(result.timestamp)
            )
            self.forecast_start.labels(*key).set(
                _parse_timestamp(result.forecast_start_time)
            )
            self.forecast_end.labels(*key).set(
                _parse_timestamp(result.forecast_end_time)
            )
            self.forecast_valid.labels(*key).set(1)
            self.execution_seconds.labels(*key).set(time.monotonic() - started)
        return result

    def refresh_expiry(self, *, now_timestamp: float | None = None) -> bool:
        """주(primary) 대상의 예측 유효성을 반환합니다 (헬스체크 계약 유지)."""
        return self._refresh_expiry_for(self.metric_labels, now_timestamp=now_timestamp)

    def refresh_all_expiry(self, *, now_timestamp: float | None = None) -> None:
        for key in self.target_keys:
            self._refresh_expiry_for(key, now_timestamp=now_timestamp)

    def _refresh_expiry_for(
        self, key: tuple[str, str], *, now_timestamp: float | None = None
    ) -> bool:
        now = now_timestamp if now_timestamp is not None else time.time()
        target_settings = self._settings_by_key[key]
        with self.lock:
            state = self._states[key]
            latest = state.latest
            if latest is None:
                state.valid = False
            else:
                age = now - _parse_timestamp(latest.timestamp)
                if age > target_settings.forecast_ttl_seconds:
                    state.valid = False
                    state.last_error = (
                        f"forecast expired after {age:.1f}s "
                        f"(ttl={target_settings.forecast_ttl_seconds}s)"
                    )
            if not state.valid:
                self.scaling_replicas.labels(*key).set(0)
                self.forecast_valid.labels(*key).set(0)
            return state.valid

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

    def prediction_response(self, namespace: str, deployment: str) -> dict:
        key = (namespace, deployment)
        if key not in self._settings_by_key:
            raise KeyError(key)
        self._refresh_expiry_for(key)
        with self.lock:
            state = self._states[key]
            if not state.valid or state.latest is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=state.last_error or "forecast is not available",
                )
            result = state.latest
            target_settings = self._settings_by_key[key]
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
                "mode": target_settings.mode,
                "model_id": target_settings.model_id,
                "source_points": result.source_points,
            }


def create_app(
    settings: ForecastSettings | None = None,
    runtime: ForecastRuntime | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    if runtime is not None:
        configured_runtime = runtime
        configured_settings = configured_runtime.settings
    else:
        primary_settings = settings or ForecastSettings.from_environment()
        # settings가 명시적으로 전달된 경우(테스트 등)는 단일 대상 그대로 사용하고,
        # 환경변수 기반 기본 경로에서만 CHRONOS_TARGETS로 추가 워크로드를 확장합니다.
        targets = (
            [primary_settings]
            if settings is not None
            else parse_targets_from_environment(primary_settings)
        )
        configured_settings = targets[0]
        configured_runtime = ForecastRuntime(
            configured_settings, extra_targets=targets[1:]
        )

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
        return {
            "status": "alive",
            "mode": configured_settings.mode,
            "model_id": configured_settings.model_id,
        }

    @application.get("/health/ready")
    def ready() -> dict:
        if configured_settings.mode == "disabled":
            return {
                "status": "ready",
                "mode": "disabled",
                "model_id": configured_settings.model_id,
            }
        if not configured_runtime.refresh_expiry():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=configured_runtime.primary_state.last_error
                or "no valid forecast is available",
            )
        return {
            "status": "ready",
            "mode": configured_settings.mode,
            "model_id": configured_settings.model_id,
        }

    @application.get("/predict/{namespace}/{deployment}")
    def predict(namespace: str, deployment: str) -> dict:
        try:
            return configured_runtime.prediction_response(namespace, deployment)
        except KeyError:
            configured_targets = ", ".join(
                f"{ns}/{dep}" for ns, dep in configured_runtime.target_keys
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "unsupported forecast target; configured targets are "
                    f"{configured_targets}"
                ),
            )

    @application.get("/metrics")
    def metrics() -> Response:
        configured_runtime.refresh_all_expiry()
        return Response(
            content=generate_latest(configured_runtime.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return application


app = create_app()
