# ===========================
# 공식 Kubernetes Gateway API CRD 설치
# ===========================
data "http" "gateway_api_crds_yaml" {
  url = "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml"
}

data "kubectl_file_documents" "gateway_api_crds" {
  content = data.http.gateway_api_crds_yaml.response_body
}

resource "kubectl_manifest" "gateway_api_crds" {
  for_each          = data.kubectl_file_documents.gateway_api_crds.manifests
  yaml_body         = each.value
  server_side_apply = true
  force_conflicts   = true
}

# ===========================
# AWS LBC 전용 Gateway CRD 설치
# ===========================
data "http" "lbc_gateway_crds_yaml" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.4.0/config/crd/gateway/gateway-crds.yaml"
}

data "kubectl_file_documents" "lbc_gateway_crds" {
  content = data.http.lbc_gateway_crds_yaml.response_body
}

resource "kubectl_manifest" "lbc_gateway_crds" {
  for_each          = data.kubectl_file_documents.lbc_gateway_crds.manifests
  yaml_body         = each.value
  server_side_apply = true
  force_conflicts   = true
  depends_on        = [kubectl_manifest.gateway_api_crds]
}

data "aws_iam_role" "aws_lb_controller" {
  name = "project03-eks-aws-lb-controller"
}

# ALB Controller를 Helm으로 EKS에 설치
resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "3.4.0"

  set = [
    {
      name  = "clusterName"
      value = "project03-eks"
    },
    {
      name  = "serviceAccount.create"
      value = "true"
    },
    {
      name  = "serviceAccount.name"
      value = "aws-load-balancer-controller"
    },
    {
      name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
      value = data.aws_iam_role.aws_lb_controller.arn
    },
    {
      name  = "controllerConfig.featureGates.ALBGatewayAPI"
      value = "true"
    }
  ]

  depends_on = [
    kubectl_manifest.gateway_api_crds,
    kubectl_manifest.lbc_gateway_crds
  ]
}
