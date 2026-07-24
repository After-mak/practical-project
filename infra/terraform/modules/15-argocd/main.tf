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

  set = [
    {
      name  = "crds.install"
      value = "true"
    }
  ]
  
  # 관리자 비밀번호 Hash를 bcrypt()로 매 Plan마다 다시 만들면 salt가 달라져
  # 실제 설정 변경이 없어도 Helm Release가 계속 변경 대상으로 표시됩니다.
  # 기존 Release의 비밀번호는 유지하고, 신규 설치 시에는 Chart가 생성하는
  # 초기 관리자 Secret을 별도의 비밀번호 관리 절차로 변경합니다.
  lifecycle {
    ignore_changes = [set]
  }
}

# ----------------------------------------------------------------
# Argo Rollouts Helm 설치
# ----------------------------------------------------------------
resource "helm_release" "argo_rollouts" {
  name             = "argo-rollouts"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-rollouts"
  version          = "2.38.0"
  namespace        = "argo-rollouts"
  create_namespace = true

  # ArgoCD가 다 설치된 후 안전하게 배포되도록 의존성 지정
  depends_on = [
    helm_release.argocd
  ]
}