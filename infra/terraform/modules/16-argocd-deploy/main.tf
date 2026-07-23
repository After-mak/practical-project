terraform {
  required_providers {
    kubectl = { source = "alekc/kubectl" }
  }
}

resource "kubectl_manifest" "prometheus_stack" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    targetRevision: 87.10.1
    helm:
      values: |
        ${indent(8, templatefile("${path.module}/prometheus/my-values.yaml.tpl", { grafana_admin_password = var.grafana_admin_password }))}
  destination:
    server: https://kubernetes.default.svc
    namespace: prometheus
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
  ignoreDifferences:
  - group: admissionregistration.k8s.io
    kind: ValidatingWebhookConfiguration
    name: prometheus-stack-kube-prom-admission
    jsonPointers:
    - /webhooks/0/clientConfig/caBundle
  - group: admissionregistration.k8s.io
    kind: MutatingWebhookConfiguration
    name: prometheus-stack-kube-prom-admission
    jsonPointers:
    - /webhooks/0/clientConfig/caBundle
YAML
}

resource "kubectl_manifest" "mak_app" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mak-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/mak-app
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

resource "kubectl_manifest" "postgres_app" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/postgres
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

resource "kubectl_manifest" "sample_fastapi" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: sample-fastapi
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/sample-fastapi
    helm:
      values: |
        image:
          repository: ${var.sample_fastapi_image_repository}
        redis:
          host: ${var.sample_fastapi_redis_host}
          port: ${var.sample_fastapi_redis_port}
  destination:
    server: https://kubernetes.default.svc
    namespace: sample-fastapi
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

resource "kubectl_manifest" "argocd_config" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: argocd-config
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/argocd-config
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}
