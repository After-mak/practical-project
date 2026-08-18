terraform {
  required_providers {
    kubectl = { source = "alekc/kubectl" }
    null    = { source = "hashicorp/null" }
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

# ----------------------------------------------------------------
# Reflector: krr-data-db-app Secret(finops 네임스페이스)을 Grafana가 있는
# prometheus 네임스페이스로 복제하기 위한 컨트롤러. CNPG가 비밀번호를 재발급해도
# 자동으로 따라가도록, Terraform이 값을 한 번 읽어 복사하는 대신 클러스터 안에서
# 지속적으로 동기화되는 방식을 씁니다.
# ----------------------------------------------------------------
resource "kubectl_manifest" "reflector" {
  yaml_body = <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: reflector
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://emberstack.github.io/helm-charts
    chart: reflector
    targetRevision: "10.0.65"
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
YAML
}

# krr-data-db-app Secret에 Reflector 어노테이션을 붙여 prometheus 네임스페이스로
# 자동 복제되도록 설정합니다. CNPG Operator가 이 Secret을 비동기로 생성하므로
# (ArgoCD Application이 Synced 상태가 됐다고 Secret이 바로 존재한다는 보장이 없음),
# kubectl로 정식 리소스를 만드는 대신 Secret이 나타날 때까지 재시도하며 기다렸다가
# 어노테이션을 붙입니다 (최대 5분, 10초 간격).
resource "null_resource" "krr_data_db_app_reflection" {
  triggers = {
    # 매 apply마다 재실행 - annotate --overwrite라 멱등하고, 누군가 어노테이션을
    # 지워도(또는 Secret이 재생성돼도) 다음 apply에서 다시 붙습니다.
    always_run = timestamp()
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      aws eks update-kubeconfig --name project03-eks --region ap-northeast-2 --profile ${var.aws_profile}

      for i in $(seq 1 30); do
        if kubectl -n finops get secret krr-data-db-app >/dev/null 2>&1; then
          kubectl -n finops annotate secret krr-data-db-app --overwrite \
            reflector.v1.k8s.emberstack.com/reflection-allowed=true \
            reflector.v1.k8s.emberstack.com/reflection-auto-enabled=true \
            reflector.v1.k8s.emberstack.com/reflection-auto-namespaces=prometheus
          echo "[reflection] krr-data-db-app Secret에 어노테이션 완료"
          exit 0
        fi
        echo "[reflection] krr-data-db-app Secret이 아직 없음, 10초 후 재시도 ($i/30)"
        sleep 10
      done

      echo "[reflection] 5분 동안 krr-data-db-app Secret을 찾지 못했습니다. CNPG Cluster 상태를 확인하세요." >&2
      exit 1
    EOT
  }

  depends_on = [kubectl_manifest.krr_data_db, kubectl_manifest.reflector]
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
          # StoreGateway 메모리 증설 (2Gi) 
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 1000m
              memory: 2Gi
          # -----------------------------------------------------
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
