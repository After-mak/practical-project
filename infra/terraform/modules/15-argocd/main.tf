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

  # Gateway API 플러그인은 컨트롤러와 함께 고정 버전 이미지로 배포합니다.
  # 실제 적용 시 컨트롤러 Pod가 재생성되므로 별도 배포 승인이 필요합니다.
  values = [<<-YAML
    controller:
      initContainers:
        - name: copy-gateway-api-plugin
          image: ghcr.io/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi:v0.5.0@sha256:cdaf973e2f390034e293af0d4ee08611b6b6c089f1627167b4014c3bcac12a7c
          command: ["/bin/sh", "-c"]
          args:
            - cp /bin/rollouts-plugin-trafficrouter-gatewayapi /plugins/
          volumeMounts:
            - name: gateway-api-plugin
              mountPath: /plugins
      trafficRouterPlugins:
        - name: argoproj-labs/gatewayAPI
          location: file:///plugins/rollouts-plugin-trafficrouter-gatewayapi
      volumes:
        - name: gateway-api-plugin
          emptyDir: {}
      volumeMounts:
        - name: gateway-api-plugin
          mountPath: /plugins
    providerRBAC:
      providers:
        gatewayAPI: true
      additionalRules:
        - apiGroups: ["gateway.networking.k8s.io"]
          resources: ["httproutes"]
          verbs: ["get", "list", "update", "patch"]
    YAML
  ]

  # ArgoCD가 다 설치된 후 안전하게 배포되도록 의존성 지정
  depends_on = [
    helm_release.argocd
  ]
}