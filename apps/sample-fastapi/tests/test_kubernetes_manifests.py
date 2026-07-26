"""Prometheus 수집에 필요한 Kubernetes selector와 port 연결을 검증합니다."""

import json
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


def test_sample_fastapi_grafana_dashboard_has_scoped_workload_panels():
    values = load_yaml(PROMETHEUS_VALUES)
    dashboard_json = values["grafana"]["dashboards"]["finops-dashboards"][
        "sample-fastapi-workload"
    ]["json"]
    dashboard = json.loads(dashboard_json)
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    expected_titles = {
        "Redis Queue State",
        "Worker Deployment Replicas",
        "KEDA HPA Current vs Desired",
        "Worker Queue Events",
        "Sample Pod CPU Usage",
        "Sample Pod Memory Working Set",
    }
    assert dashboard["uid"] == "sample-fastapi-workload"
    assert set(panels) == expected_titles

    expressions = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel["targets"]
    ]
    assert all('namespace="sample-fastapi"' in expression for expression in expressions)
    assert any("sample_queue_length" in expression for expression in expressions)
    assert any("sample_queue_processing_length" in expression for expression in expressions)
    assert any("sample_queue_dead_letter_length" in expression for expression in expressions)
    hpa_expressions = [
        expression for expression in expressions if "horizontalpodautoscaler" in expression
    ]
    assert len(hpa_expressions) == 2
    assert all(
        'horizontalpodautoscaler="keda-hpa-sample-worker"' in expression
        for expression in hpa_expressions
    )


def test_only_api_receives_load_test_token_from_secret():
    api = load_yaml(K8S_DIR / "fastapi-deployment.yaml")
    worker = load_yaml(K8S_DIR / "worker-deployment.yaml")
    api_env_from = api["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    worker_env_from = worker["spec"]["template"]["spec"]["containers"][0]["envFrom"]

    secret_reference = {
        "secretRef": {
            "name": "sample-fastapi-load-test",
            "optional": True,
        }
    }
    assert secret_reference in api_env_from
    assert secret_reference not in worker_env_from


def test_workload_scenarios_have_unique_selectors_and_resource_profiles():
    documents = list(
        yaml.safe_load_all(
            (K8S_DIR / "workload-scenarios.yaml").read_text(encoding="utf-8")
        )
    )
    deployments = {
        document["metadata"]["labels"]["workload-type"]: document
        for document in documents
        if document["kind"] == "Deployment"
    }

    assert set(deployments) == {"baseline", "overallocated", "idle", "spike"}
    for workload_type, deployment in deployments.items():
        labels = deployment["spec"]["template"]["metadata"]["labels"]
        assert labels["workload-type"] == workload_type
        assert_labels_match(deployment["spec"]["selector"]["matchLabels"], labels)
        assert "resources" in deployment["spec"]["template"]["spec"]["containers"][0]

    assert (
        deployments["overallocated"]["spec"]["template"]["spec"]["containers"][0][
            "resources"
        ]["requests"]
        == {"cpu": "500m", "memory": "512Mi"}
    )
    assert deployments["idle"]["spec"]["replicas"] == 3
