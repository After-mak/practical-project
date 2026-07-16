# terraform {
#   required_providers {
#     kubernetes = {
#       source  = "hashicorp/kubernetes"
#       version = "~> 2.30" 
#     }
#     helm = {
#       source  = "hashicorp/helm"
#       version = "~> 2.14"
#     }
#   }
# }

# provider "kubernetes" {
#   config_path = "~/.kube/config"
# }

# provider "helm" {
#   kubernetes {
#     config_path = "~/.kube/config"
#   }
# }

# # ----------------------------------------------------------------
# # [단계 1] 쿠버네티스 표준 Gateway API CRD 설치(Gateway,HTTPRoute 목적)
# # ----------------------------------------------------------------
# # NGINX Gateway Fabric이 동작하려면 클러스터에 Gateway API 표준 규격이 선언되어 있어야 합니다.
# # 공식 릴리즈된 표준 CRD를 먼저 클러스터에 적용합니다.
# resource "helm_release" "gateway_api_crds" {
#   name             = "gateway-api-crds"
#   repository       = "https://helm.nginx.com/stable"
#   chart            = "gateway-api-crds"
#   version          = "1.1.0" # 선호하는 Gateway API 버전 규격 사용
#   namespace        = "gateway-system"
# }

# # ----------------------------------------------------------------
# # [단계 2] NGINX Gateway Fabric 설치 (기존 nginx-ingress 대체)
# # ----------------------------------------------------------------
# resource "helm_release" "nginx_gateway" {
#   name             = "nginx-gateway"
#   repository       = "https://helm.nginx.com/stable"
#   chart            = "nginx-gateway-fabric"
#   version          = "1.3.0" # 최신 안정화 버전
#   namespace        = "nginx-gateway"
#   create_namespace = true

#   # CRD가 먼저 설치 완료된 후 헬름 차트가 배포되어야 하므로 의존성을 명시합니다.
#   depends_on = [helm_release.gateway_api_crds]
# }

# # ----------------------------------------------------------------
# # [단계 3] 인프라 관점의 진입문(Gateway) 리소스 생성
# # ----------------------------------------------------------------
# # 외부 L7 로드밸런서를 생성하고 80번 포트를 열어 모든 네임스페이스의 Route 규칙을 허용합니다.
# resource "kubernetes_manifest" "k8s_gateway" {
#   manifest = {
#     apiVersion = "gateway.networking.k8s.io/v1"
#     kind       = "Gateway"
#     metadata = {
#       name      = "external-gateway"
#       namespace = "nginx-gateway"
#     }
#     spec = {
#       gatewayClassName = "nginx" # NGINX Gateway Fabric이 제공하는 클래스명 지정
#       listeners = [
#         {
#           name     = "http"
#           protocol = "HTTP"
#           port     = 80
#           allowedRoutes = {
#             namespaces = {
#               from = "All" # 다른 네임스페이스(예: argocd)에 있는 HTTPRoute도 바인딩 가능하게 설정
#             }
#           }
#         }
#       ]
#     }
#   }

#   # NGINX Gateway Fabric 컨트롤러가 먼저 띄워져 있어야 이 진입문을 활성화할 수 있습니다.
#   depends_on = [helm_release.nginx_gateway]
# }