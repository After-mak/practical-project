# ----------------------------------------------------------------
# ArgoCD Helm 설치 (기존 코드 유지 및 최적화)
# ----------------------------------------------------------------
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.1.2"
  namespace        = "argocd"
  create_namespace = true

  values = [file("${path.module}/my-values.yaml")]

  set {
    name  = "configs.secret.argocdServerAdminPassword"
    value = bcrypt("@abcd1234")
  }
}

