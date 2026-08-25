"""Prometheus/Thanos 시계열을 Chronos 모델로 예측하는 핵심 로직입니다.

이 모듈은 HTTP 서버와 분리되어 있어 CLI, 단위 테스트, Kubernetes 서비스가 같은
예측 구현을 재사용할 수 있습니다. 무거운 torch/chronos 의존성은 실제 예측 시점에
지연 로딩하므로 설정·API 테스트는 모델 설치 없이도 실행할 수 있습니다.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence


VALID_MODES = {"disabled", "shadow", "active"}


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class ForecastSettings:
    prometheus_url: str = "http://localhost:9090"
    target_deployment: str = "sample-worker"
    target_namespace: str = "sample-fastapi"
    pod_pattern: str = "sample-worker-.*"
    container_name: str = "worker"
    mode: str = "shadow"
    threshold_cores: float = 0.3
    capacity_per_replica_cores: float = 0.5
    lookback_hours: float = 2.0
    prediction_length: int = 12
    step_seconds: int = 60
    min_replicas: int = 1
    max_replicas: int = 3
    forecast_interval_seconds: int = 60
    forecast_ttl_seconds: int = 120
    request_timeout_seconds: float = 10.0
    model_id: str = "amazon/chronos-2"
    fake_replicas: int | None = None
    forecast_output: str = ""

    @classmethod
    def from_environment(
        cls,
        *,
        prometheus_url_default: str = (
            "http://thanos-query.prometheus.svc.cluster.local:9090"
        ),
        deployment_default: str = "sample-worker",
        namespace_default: str = "sample-fastapi",
        container_default: str = "worker",
        pod_pattern_separator: str = "-",
        forecast_output_default: str = "",
    ) -> "ForecastSettings":
        deployment = os.environ.get(
            "CHRONOS_TARGET_DEPLOYMENT", deployment_default
        )
        mode = os.environ.get("CHRONOS_MODE", "shadow").strip().lower()
        fake_value = os.environ.get("CHRONOS_FAKE_REPLICAS", "").strip()
        settings = cls(
            prometheus_url=os.environ.get(
                "PROM_URL", prometheus_url_default
            ).rstrip("/"),
            target_deployment=deployment,
            target_namespace=os.environ.get(
                "CHRONOS_TARGET_NAMESPACE", namespace_default
            ),
            pod_pattern=os.environ.get(
                "CHRONOS_POD_PATTERN",
                f"{re.escape(deployment)}{pod_pattern_separator}.*",
            ),
            container_name=os.environ.get(
                "CHRONOS_CONTAINER", container_default
            ),
            mode=mode,
            threshold_cores=_positive_float("CHRONOS_THRESHOLD", 0.3),
            capacity_per_replica_cores=_positive_float(
                "CHRONOS_CAPACITY_PER_REPLICA", 0.5
            ),
            lookback_hours=_positive_float("CHRONOS_LOOKBACK_HOURS", 2),
            prediction_length=_positive_int("CHRONOS_PREDICTION_LENGTH", 12),
            step_seconds=_positive_int("CHRONOS_STEP_SECONDS", 60),
            min_replicas=_positive_int("CHRONOS_MIN_REPLICAS", 1),
            max_replicas=_positive_int("CHRONOS_MAX_REPLICAS", 3),
            forecast_interval_seconds=_positive_int(
                "CHRONOS_FORECAST_INTERVAL_SECONDS", 60
            ),
            forecast_ttl_seconds=_positive_int("CHRONOS_FORECAST_TTL_SECONDS", 120),
            request_timeout_seconds=_positive_float(
                "CHRONOS_REQUEST_TIMEOUT_SECONDS", 10
            ),
            model_id=os.environ.get(
                "CHRONOS_MODEL_ID", "amazon/chronos-2"
            ),
            fake_replicas=int(fake_value) if fake_value else None,
            forecast_output=os.environ.get(
                "FORECAST_FILE", forecast_output_default
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(
                f"CHRONOS_MODE must be one of {sorted(VALID_MODES)}, got {self.mode!r}"
            )
        if self.max_replicas < self.min_replicas:
            raise ValueError(
                "CHRONOS_MAX_REPLICAS must be greater than or equal to "
                "CHRONOS_MIN_REPLICAS"
            )
        if self.forecast_ttl_seconds < self.forecast_interval_seconds:
            raise ValueError(
                "CHRONOS_FORECAST_TTL_SECONDS must be greater than or equal to "
                "CHRONOS_FORECAST_INTERVAL_SECONDS"
            )
        if self.fake_replicas is not None and self.fake_replicas <= 0:
            raise ValueError("CHRONOS_FAKE_REPLICAS must be greater than zero")


def parse_targets_from_environment(
    base_settings: ForecastSettings,
) -> list[ForecastSettings]:
    """CHRONOS_TARGETS(JSON 리스트) 환경변수가 있으면 여러 타겟을 반환하고,
    없으면 base_settings 하나만 담긴 리스트를 반환해 기존 단일 타겟 동작을
    그대로 유지합니다(하위 호환).

    각 항목 형식: {"namespace": str, "deployment": str,
                  "pod_pattern": str (선택), "container": str (선택)}
    threshold/capacity/lookback/model 등 공통 설정은 base_settings를 그대로
    공유합니다.
    """

    raw = os.environ.get("CHRONOS_TARGETS", "").strip()
    if not raw:
        return [base_settings]
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"CHRONOS_TARGETS must be valid JSON: {exc}") from exc
    if not isinstance(items, list) or not items:
        raise ValueError("CHRONOS_TARGETS must be a non-empty JSON list")

    targets: list[ForecastSettings] = []
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or "namespace" not in item
            or "deployment" not in item
        ):
            raise ValueError(
                f"CHRONOS_TARGETS[{index}] must be an object with "
                "namespace/deployment"
            )
        namespace = str(item["namespace"])
        deployment = str(item["deployment"])
        pod_pattern = item.get("pod_pattern") or f"{re.escape(deployment)}-.*"
        container = item.get("container", base_settings.container_name)
        targets.append(
            replace(
                base_settings,
                target_namespace=namespace,
                target_deployment=deployment,
                pod_pattern=pod_pattern,
                container_name=container,
            )
        )
    return targets


@dataclass(frozen=True)
class ForecastResult:
    timestamp: str
    forecast_start_time: str
    forecast_end_time: str
    namespace: str
    deployment: str
    predicted_cpu_usage: float
    predicted_max_cpu_pct: float
    scale_out_needed: bool
    current_replicas: int
    predicted_replicas: int
    source_points: int

    def to_dict(self) -> dict:
        data = asdict(self)
        # 기존 alarm/generate_report.py 및 forecast_result.json 소비자와의 호환 필드입니다.
        data["pod"] = self.deployment
        return data


class ForecastModel(Protocol):
    def predict_max(self, values: Sequence[float], prediction_length: int) -> float:
        """향후 구간의 중간값 예측 중 최댓값을 반환합니다."""


class Chronos2Model:
    """Chronos2Pipeline을 한 번만 로딩해 반복 예측에 재사용합니다."""

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            import torch
            from chronos import Chronos2Pipeline

            self._pipeline = Chronos2Pipeline.from_pretrained(
                self.model_id,
                device_map="cpu",
                torch_dtype=torch.float32,
            )
        return self._pipeline

    def predict_max(self, values: Sequence[float], prediction_length: int) -> float:
        import torch

        context = torch.tensor(values, dtype=torch.float32)
        _, point_forecasts = self._get_pipeline().predict_quantiles(
            [context],
            prediction_length=prediction_length,
            quantile_levels=[0.5],
        )
        # 단변량 입력 하나이므로 첫 결과의 shape은 (1, prediction_length)입니다.
        # Chronos-2는 point forecast로 학습 quantile 0.5(중앙값)를 반환합니다.
        median_forecast = point_forecasts[0]
        return max(0.0, float(median_forecast.max().item()))


def _escape_promql(value: str) -> str:
    return value.replace("\\", r"\\").replace('"', r'\"')


def build_cpu_query(settings: ForecastSettings) -> str:
    """Replica 수와 무관한 Deployment 전체 CPU 수요 시계열을 만듭니다."""

    labels = [
        f'namespace="{_escape_promql(settings.target_namespace)}"',
        f'pod=~"{_escape_promql(settings.pod_pattern)}"',
        'container!="POD"',
    ]
    if settings.container_name:
        labels.insert(
            2,
            f'container="{_escape_promql(settings.container_name)}"',
        )
    return (
        "sum(rate(container_cpu_usage_seconds_total{"
        + ",".join(labels)
        + "}[5m]))"
    )


def fetch_cpu_series(
    settings: ForecastSettings,
    *,
    session=None,
    now: datetime | None = None,
) -> list[float]:
    if session is None:
        import requests

        session = requests
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=settings.lookback_hours)
    response = session.get(
        f"{settings.prometheus_url}/api/v1/query_range",
        params={
            "query": build_cpu_query(settings),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": f"{settings.step_seconds}s",
        },
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload!r}")

    results = payload.get("data", {}).get("result", [])
    if not results:
        raise RuntimeError(
            "Prometheus/Thanos returned no CPU data for "
            f"{settings.target_namespace}/{settings.target_deployment}"
        )

    # build_cpu_query()는 집계 결과 하나를 반환해야 합니다. 방어적으로 여러 결과가
    # 오면 동일 timestamp의 값을 합쳐 예측 입력이 임의의 첫 Pod에 종속되지 않게 합니다.
    series_by_timestamp: dict[float, float] = {}
    for result in results:
        for timestamp, value in result.get("values", []):
            numeric = float(value)
            if math.isfinite(numeric):
                key = float(timestamp)
                series_by_timestamp[key] = series_by_timestamp.get(key, 0.0) + numeric

    values = [series_by_timestamp[key] for key in sorted(series_by_timestamp)]
    if len(values) < settings.prediction_length:
        raise RuntimeError(
            f"Not enough CPU data points: got {len(values)}, "
            f"need at least {settings.prediction_length}"
        )
    return values


class ForecastEngine:
    def __init__(
        self,
        settings: ForecastSettings,
        model: ForecastModel | None = None,
        *,
        session=None,
        current_replicas_provider: Callable[[], int] | None = None,
        preserve_current_when_below_threshold: bool = False,
        clamp_to_max_replicas: bool = True,
    ):
        self.settings = settings
        self.model = model or Chronos2Model(settings.model_id)
        self.session = session
        self.current_replicas_provider = current_replicas_provider
        self.preserve_current_when_below_threshold = (
            preserve_current_when_below_threshold
        )
        self.clamp_to_max_replicas = clamp_to_max_replicas

    def forecast(self, *, now: datetime | None = None) -> ForecastResult:
        generated_at = now or datetime.now(timezone.utc)
        if self.settings.fake_replicas is not None:
            values = []
            predicted_cpu = (
                self.settings.fake_replicas
                * self.settings.capacity_per_replica_cores
            )
        else:
            values = fetch_cpu_series(
                self.settings, session=self.session, now=generated_at
            )
            predicted_cpu = self.model.predict_max(
                values, self.settings.prediction_length
            )
        current_replicas = (
            self.current_replicas_provider()
            if self.current_replicas_provider is not None
            else self.settings.min_replicas
        )
        scale_out_needed = predicted_cpu > self.settings.threshold_cores
        if self.preserve_current_when_below_threshold and not scale_out_needed:
            predicted_replicas = current_replicas
        else:
            predicted_replicas = max(
                self.settings.min_replicas,
                math.ceil(
                    predicted_cpu
                    / self.settings.capacity_per_replica_cores
                ),
            )
            if self.clamp_to_max_replicas:
                predicted_replicas = min(
                    self.settings.max_replicas, predicted_replicas
                )
        forecast_end = generated_at + timedelta(
            seconds=self.settings.prediction_length * self.settings.step_seconds
        )
        result = ForecastResult(
            timestamp=generated_at.isoformat(),
            forecast_start_time=generated_at.isoformat(),
            forecast_end_time=forecast_end.isoformat(),
            namespace=self.settings.target_namespace,
            deployment=self.settings.target_deployment,
            predicted_cpu_usage=round(predicted_cpu, 6),
            predicted_max_cpu_pct=round(
                predicted_cpu / self.settings.capacity_per_replica_cores * 100,
                3,
            ),
            scale_out_needed=scale_out_needed,
            current_replicas=current_replicas,
            predicted_replicas=predicted_replicas,
            source_points=len(values),
        )
        self._write_result(result)
        return result

    def _write_result(self, result: ForecastResult) -> None:
        if not self.settings.forecast_output:
            return
        output = Path(self.settings.forecast_output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_current_replicas(settings: ForecastSettings) -> int:
    """기존 로컬 파이프라인처럼 kubectl로 현재 Deployment replica를 조회합니다."""

    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployment",
                settings.target_deployment,
                "-n",
                settings.target_namespace,
                "-o",
                "jsonpath={.spec.replicas}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return int(result.stdout.strip())
    except Exception as exc:
        print(f"현재 replica 수 조회 실패, 기본값 1 사용: {exc}")
        return 1


def legacy_cli_settings_from_environment() -> ForecastSettings:
    """run_pipeline.sh에서 사용하던 기존 기본값을 그대로 유지합니다."""

    return ForecastSettings.from_environment(
        prometheus_url_default="http://localhost:9090",
        deployment_default="test-overprovisioned",
        namespace_default="default",
        container_default="",
        pod_pattern_separator="",
        forecast_output_default="~/k8s-manifest/forecast_result.json",
    )


def main() -> int:
    settings = legacy_cli_settings_from_environment()
    if settings.mode == "disabled":
        print("CHRONOS_MODE=disabled: forecast skipped")
        return 0
    started = time.monotonic()
    result = ForecastEngine(
        settings,
        current_replicas_provider=lambda: get_current_replicas(settings),
        preserve_current_when_below_threshold=True,
        clamp_to_max_replicas=False,
    ).forecast()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    print(f"forecast completed in {time.monotonic() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
