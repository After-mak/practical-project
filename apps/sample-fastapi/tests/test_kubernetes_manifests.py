"""Prometheus 수집에 필요한 Kubernetes selector와 port 연결을 검증합니다."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
K8S_DIR = ROOT / "k8s" / "sample-fastapi"
PROMETHEUS_VALUES = (
    ROOT
    / "infra"
    / "terraform"
    / "modules"
    / "16-argocd-deploy"
    / "prometheus"
    / "my-values.yaml.tpl"
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def assert_labels_match(selector: dict, labels: dict) -> None:
    assert all(labels.get(key) == value for key, value in selector.items())


def test_worker_keeps_one_baseline_replica():
    deployment = load_yaml(K8S_DIR / "worker-deployment.yaml")

    assert deployment["spec"]["replicas"] == 1


def test_fastapi_service_monitor_selects_service_and_named_port():
    service = load_yaml(K8S_DIR / "fastapi-service.yaml")
    monitor = load_yaml(K8S_DIR / "fastapi-servicemonitor.yaml")

    assert_labels_match(
        monitor["spec"]["selector"]["matchLabels"], service["metadata"]["labels"]
    )
    assert monitor["spec"]["endpoints"][0]["port"] == service["spec"]["ports"][0]["name"]


def test_worker_service_and_monitor_select_worker_pod_and_named_port():
    deployment = load_yaml(K8S_DIR / "worker-deployment.yaml")
    service = load_yaml(K8S_DIR / "worker-service.yaml")
    monitor = load_yaml(K8S_DIR / "worker-servicemonitor.yaml")

    assert_labels_match(
        service["spec"]["selector"],
        deployment["spec"]["template"]["metadata"]["labels"],
    )
    assert_labels_match(
        monitor["spec"]["selector"]["matchLabels"], service["metadata"]["labels"]
    )
    assert monitor["spec"]["endpoints"][0]["port"] == service["spec"]["ports"][0]["name"]


def test_prometheus_selects_sample_namespace_and_service_monitors():
    values = load_yaml(PROMETHEUS_VALUES)
    prometheus_spec = values["prometheus"]["prometheusSpec"]

    assert prometheus_spec["serviceMonitorSelectorNilUsesHelmValues"] is False
    # Empty selectors intentionally allow Prometheus to discover both the
    # built-in monitors and ServiceMonitors from every namespace.
    assert prometheus_spec["serviceMonitorSelector"] == {}
    assert prometheus_spec["serviceMonitorNamespaceSelector"] == {}
