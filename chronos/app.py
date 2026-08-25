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
    ForecastEngine,
    ForecastResult,
    ForecastSettings,
    parse_targets_from_environment,
)

logger = logging.getLogger("chronos-service")


def _parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


TargetKey = tuple[str, str]


def _target_key(settings: ForecastSettings) -> TargetKey:
    return settings.target_namespace, settings.target_deployment


@dataclass
class RuntimeState:
    latest: ForecastResult | None = None
    valid: bool = False
    last_error: str | None = None


class ForecastRuntime:
    """하나 이상의 예측 대상(Target)을 관리합니다.

    기존 단일 타겟 동작과의 호환을 위해 `settings`는 계속 "기본(primary)" 타겟을
    의미합니다. `additional_targets`를 넘기면 같은 Prometheus 레지스트리 안에서
    타겟별로 라벨(namespace, deployment)이 분리된 메트릭을 동시에 노출합니다.
    """

    def __init__(
        self,
        settings: ForecastSettings,
        forecast: Callable[[], ForecastResult] | None = None,
        *,
        registry: CollectorRegistry | None = None,
        additional_targets: Sequence[ForecastSettings] = (),
    ):
        self.settings = settings
        self.registry = registry or CollectorRegistry()
        self.targets: list[ForecastSettings] = [settings, *additional_targets]

        target_keys = [_target_key(t) for t in self.targets]
        if len(set(target_keys)) != len(target_keys):
            raise ValueError(
                "CHRONOS_TARGETS에 namespace/deployment 조합이 중복됩니다"
            )
        if forecast is not None and len(self.targets) > 1:
            raise ValueError("forecast 오버라이드는 단일 타겟에서만 지원합니다")

        self._forecast_fns: dict[TargetKey, Callable[[], ForecastResult]] = {
            _target_key(t): (forecast or ForecastEngine(t).forecast)
            for t in self.targets
        }
        self._states: dict[TargetKey, RuntimeState] = {
            key: RuntimeState() for key in target_keys
        }
        self._settings_by_key: dict[TargetKey, ForecastSettings] = {
            _target_key(t): t for t in self.targets
        }

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
        self.model_info = Gauge(
            "chronos_model_info",
            "Configured Chronos model",
            labelnames=("model_id",),
            registry=self.registry,
        )
        self.model_info.labels(model_id=settings.model_id).set(1)
        for name in ("disabled", "shadow", "active"):
            self.mode.labels(mode=name).set(1 if settings.mode == name else 0)

        for target in self.targets:
            self._set_inactive_metrics(target)

    @property
    def target_keys(self) -> set[TargetKey]:
        return set(self._states)

    @property
    def metric_labels(self) -> TargetKey:
        # 기존 단일 타겟 코드/테스트와의 호환을 위해 기본(primary) 타겟 라벨을 반환합니다.
        return _target_key(self.settings)

    @property
    def state(self) -> RuntimeState:
        # 기존 단일 타겟 코드와의 호환을 위한 기본(primary) 타겟 상태입니다.
        return self._states[_target_key(self.settings)]

    def _set_inactive_metrics(self, target: ForecastSettings) -> None:
        labels = _target_key(target)
        self.predicted_cpu.labels(*labels).set(0)
        self.predicted_replicas.labels(*labels).set(target.min_replicas)
        self.scaling_replicas.labels(*labels).set(0)
        self.forecast_timestamp.labels(*labels).set(0)
        self.forecast_start.labels(*labels).set(0)
        self.forecast_end.labels(*labels).set(0)
        self.forecast_valid.labels(*labels).set(0)
        self.execution_seconds.labels(*labels).set(0)

    def run_once_for(self, target: ForecastSettings) -> ForecastResult | None:
        key = _target_key(target)
        state = self._states[key]
        if target.mode == "disabled":
            with self.lock:
                state.valid = False
                state.last_error = None
                self._set_inactive_metrics(target)
            return None
        started = time.monotonic()
        try:
            result = self._forecast_fns[key]()
        except Exception as exc:  # noqa: BLE001 - 타겟별 예측 실패를 서로 격리합니다
            logger.exception("Chronos forecast failed for %s/%s", *key)
            with self.lock:
                state.valid = False
                state.last_error = str(exc)
                self.scaling_replicas.labels(*key).set(0)
                self.forecast_valid.labels(*key).set(0)
                self.execution_seconds.labels(*key).set(time.monotonic() - started)
                self.errors.labels(*key).inc()
            return None
        with self.lock:
            state.latest = result
            state.valid = True
            state.last_error = None
            self.predicted_cpu.labels(*key).set(result.predicted_cpu_usage)
            self.predicted_replicas.labels(*key).set(result.predicted_replicas)
            self.scaling_replicas.labels(*key).set(
                result.predicted_replicas if target.mode == "active" else 0
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

    def run_once(self) -> ForecastResult | None:
        # 기존 단일 타겟 테스트/CLI와의 호환을 위해 기본(primary) 타겟만 실행합니다.
        return self.run_once_for(self.settings)

    def run_all(self) -> None:
        for target in self.targets:
            self.run_once_for(target)

    def refresh_expiry_for(
        self, target: ForecastSettings, *, now_timestamp: float | None = None
    ) -> bool:
        now = now_timestamp if now_timestamp is not None else time.time()
        key = _target_key(target)
        state = self._states[key]
        with self.lock:
            latest = state.latest
            if latest is None:
                state.valid = False
            else:
                age = now - _parse_timestamp(latest.timestamp)
                if age > target.forecast_ttl_seconds:
                    state.valid = False
                    state.last_error = (
                        f"forecast expired after {age:.1f}s "
                        f"(ttl={target.forecast_ttl_seconds}s)"
                    )
            if not state.valid:
                self.scaling_replicas.labels(*key).set(0)
                self.forecast_valid.labels(*key).set(0)
            return state.valid

    def refresh_expiry(self, *, now_timestamp: float | None = None) -> bool:
        return self.refresh_expiry_for(self.settings, now_timestamp=now_timestamp)

    def any_target_ready(self) -> bool:
        """하나 이상의 타겟이 유효하면 Pod 전체는 Ready로 간주합니다.

        타겟 하나(예: 새로 추가한 sample-worker)가 과거 데이터 부족 등으로
        일시적으로 실패해도, 이미 정상 동작 중인 다른 타겟(mak-app-rollout)까지
        Pod가 NotReady가 되어 Service에서 빠지는 일을 막기 위한 설계입니다.
        """
        return any(self.refresh_expiry_for(target) for target in self.targets)

    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(
            target=self._run_loop, name="chronos-forecast-loop", daemon=True
        )
        self.thread.start()

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            self.run_all()
            self.stop_event.wait(self.settings.forecast_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def prediction_response(self, namespace: str, deployment: str) -> dict:
        key = (namespace, deployment)
        target = self._settings_by_key[key]
        self.refresh_expiry_for(target)
        with self.lock:
            state = self._states[key]
            if not state.valid or state.latest is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=state.last_error or "forecast is not available",
                )
            result = state.latest
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
                "mode": target.mode,
                "model_id": target.model_id,
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
        configured_settings = settings or runtime.settings
    else:
        base_settings = settings or ForecastSettings.from_environment()
        all_targets = parse_targets_from_environment(base_settings)
        configured_settings = all_targets[0]
        configured_runtime = ForecastRuntime(
            configured_settings, additional_targets=all_targets[1:]
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
            "targets": [
                f"{ns}/{dep}" for ns, dep in sorted(configured_runtime.target_keys)
            ],
        }

    @application.get("/health/ready")
    def ready() -> dict:
        all_disabled = all(t.mode == "disabled" for t in configured_runtime.targets)
        if all_disabled:
            return {
                "status": "ready",
                "mode": "disabled",
                "model_id": configured_settings.model_id,
            }
        if not configured_runtime.any_target_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="no configured target has a valid forecast",
            )
        return {
            "status": "ready",
            "mode": configured_settings.mode,
            "model_id": configured_settings.model_id,
        }

    @application.get("/predict/{namespace}/{deployment}")
    def predict(namespace: str, deployment: str) -> dict:
        if (namespace, deployment) not in configured_runtime.target_keys:
            configured = ", ".join(
                f"{ns}/{dep}" for ns, dep in sorted(configured_runtime.target_keys)
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "unsupported forecast target; configured targets are "
                    f"{configured}"
                ),
            )
        return configured_runtime.prediction_response(namespace, deployment)

    @application.get("/metrics")
    def metrics() -> Response:
        for target in configured_runtime.targets:
            configured_runtime.refresh_expiry_for(target)
        return Response(
            content=generate_latest(configured_runtime.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return application


app = create_app()
