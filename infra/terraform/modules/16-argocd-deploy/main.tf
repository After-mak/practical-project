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
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    targetRevision: 87.10.1
    helm:
      values: |
        ${indent(8, templatefile("${path.module}/prometheus/my-values.yaml.tpl", {
  grafana_admin_password = var.grafana_admin_password
  enable_krr_demo_seed   = var.enable_krr_demo_seed
  krr_demo_seed_image    = var.krr_demo_seed_image
}))}
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

resource "kubectl_manifest" "keda" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: keda
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://kedacore.github.io/charts
    chart: keda
    targetRevision: 2.20.1
    helm:
      releaseName: keda
  destination:
    server: https://kubernetes.default.svc
    namespace: keda
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
YAML
}

# 1. Frontend 애플리케이션 (프론트엔드 관련 리소스 담당 네임스페이스)
resource "kubectl_manifest" "mak_frontend" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mak-frontend
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/mak-app    # 또는 프론트엔드 전용 차트 경로로 분리 가능
    helm:
      values: |
        # 프론트엔드 전용 values 설정 (필요시)
        components:
          backend: false
          frontend: true
        secrets:
          existingSecret: ${var.bank_jwt_secret_name}
  destination:
    server: https://kubernetes.default.svc
    namespace: frontend
  ignoreDifferences:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      jqPathExpressions:
        - .spec.rules[].backendRefs[].weight
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

# 2. Backend 애플리케이션 (마이크로서비스 및 DB 연동 서비스 담당)
resource "kubectl_manifest" "mak_backend" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mak-backend
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/mak-app    # 또는 백엔드 전용 차트 경로로 분리 가능
    helm:
      values: |
        components:
          backend: true
          frontend: false
        secrets:
          existingSecret: ${var.bank_jwt_secret_name}
  destination:
    server: https://kubernetes.default.svc
    namespace: backend
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
  finalizers:
  - resources-finalizer.argocd.argoproj.io
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

resource "kubectl_manifest" "chronos_model" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: chronos-model
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/chronos
    helm:
      values: |
        image:
          repository: ${var.chronos_model_image_repository}
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - SkipDryRunOnMissingResource=true
YAML
}

resource "kubectl_manifest" "grafana_finops_dashboard" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: grafana-finops-dashboard
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/grafana-finops-dashboard
    helm:
      valueFiles:
      - values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: prometheus
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

resource "kubectl_manifest" "finops_analyzer" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: finops-analyzer
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/finops
    helm:
      values: |
        image:
          repository: ${var.finops_analyzer_image_repository}
  destination:
    server: https://kubernetes.default.svc
    namespace: finops
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
  finalizers:
  - resources-finalizer.argocd.argoproj.io
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

# ----------------------------------------------------------------
# CNPG(CloudNativePG) Database 클러스터 배포 (GitOps 연동)
# - mak-argocd-deploy 저장소의 cnpg-db 폴더(차트)를 읽어와서
#   EKS 내부에 DB 인스턴스와 백업 설정을 자동으로 띄웁니다.
# ----------------------------------------------------------------
resource "kubectl_manifest" "cnpg_db" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cnpg-db
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/cnpg-db
  destination:
    server: https://kubernetes.default.svc
    namespace: backend
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

# ----------------------------------------------------------------
# FinOps KRR Logs 전용 CNPG Database 클러스터 배포 (GitOps 연동)
# ----------------------------------------------------------------
resource "kubectl_manifest" "krr_data_db" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: krr-data-db
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/krr-data-db
  destination:
    server: https://kubernetes.default.svc
    namespace: finops
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

resource "kubectl_manifest" "karpenter_resources" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: karpenter
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/karpenter
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - ServerSideApply=true
YAML
}

resource "kubectl_manifest" "tg_gateway" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tg-gateway
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/After-mak/mak-argocd-deploy.git
    targetRevision: main
    path: charts/tg-gateway
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

resource "kubectl_manifest" "thanos" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: thanos
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://charts.bitnami.com/bitnami
    chart: thanos
    targetRevision: 15.7.0
    helm:
      values: |
        image:
          registry: quay.io
          repository: thanos/thanos
          tag: v0.35.1
        query:
          enabled: true
          replicaCount: 1
          # Prometheus Sidecar와 Thanos Store를 연결
          stores:
            - "prometheus-operated.prometheus.svc.cluster.local:10901"
            - "thanos-storegateway.prometheus.svc.cluster.local:10901"
          serviceAccount:
            create: true
            name: thanos-query
            annotations:
              eks.amazonaws.com/role-arn: "arn:aws:iam::372666940978:role/project03-thanos-s3-role"
        storegateway:
          enabled: true
          replicaCount: 1
          persistence:
            storageClass: "ebs-gp3"
          serviceAccount:
            create: true
            name: thanos-store
            # 파드에 IRSA IAM 토큰을 자동으로 마운트하도록 설정
            automountServiceAccountToken: true
            annotations:
              eks.amazonaws.com/role-arn: "arn:aws:iam::372666940978:role/project03-thanos-s3-role"
        objstoreConfig: |-
          type: s3
          config:
            bucket: project03-thanos-metrics-83154bf5
            endpoint: s3.ap-northeast-2.amazonaws.com
            region: ap-northeast-2
        compactor:
          # enabled: false
          enabled: true
          retentionResolutionRaw: 30d   # 원본(상세) 데이터 30일 보존 후 삭제
          retentionResolution5m: 30d    # 5분 축소 데이터 30일 보존
          retentionResolution1h: 30d   # 1시간 축소 데이터 30일 보존
          persistence:
            enabled: true
            storageClass: "ebs-gp3"
            size: 10Gi                  # 작업용 로컬 EBS 볼륨 생성
          # Compactor가 S3 접근 시 사용할 ServiceAccount 및 IRSA 권한 추가
          serviceAccount:
            create: true
            name: thanos-compactor
            annotations:
              eks.amazonaws.com/role-arn: "arn:aws:iam::372666940978:role/project03-thanos-s3-role"
        bucketweb:
          enabled: false
        receive:
          enabled: false
  destination:
    server: https://kubernetes.default.svc
    namespace: prometheus
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}
