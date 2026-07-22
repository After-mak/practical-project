# ===========================
# Gateway api
# ===========================
# terraform 이 helm으로 eks에 설치할 수 있게 정보 알려주는 내용
provider "helm" {
  kubernetes = {
    host                   = module.project03_eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.project03_eks.cluster_certificate_authority_data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.project03_eks.cluster_name, "--profile", var.aws_profile]
    }
  }
}
# AWS 공식 정책 문서를 JSON형태로 GitHub에서 다운로드
data "http" "aws_lb_controller_policy" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.4.0/docs/install/iam_policy.json"
}

# 공식 정책 문서를 하나의 권한으로 만들기
resource "aws_iam_policy" "aws_lb_controller" {
  name        = "${module.project03_eks.cluster_name}-aws-lb-controller"
  description = "IAM policy for AWS Load Balancer Controller"
  policy      = data.http.aws_lb_controller_policy.response_body
}


# IRSA부분 작성 (IAM Roles for Service Accounts)
# pod가 권한을 사용할 수 있게 하는 권한을 담은 증명서 만들기 / 누가 누구한테 권한을 빌릴 것인가가 명시되어있어야함
# [eks cluster 내부에 특정 pod가 aws 의 권한을 빌리기]
data "aws_iam_policy_document" "aws_lb_controller_assume" {
  statement {
    # pod가 권한달라고 할 때 조건이 맞으면 허용해주는 옵션
    effect  = "Allow"
    # 어떤 방식으로 권한을 빌릴 것인가 => pod가 사용하는 JWT token 방식으로 빌림
    actions = ["sts:AssumeRoleWithWebIdentity"]
    #eks cluster가 발급한 token만 신뢰하는 옵션
    principals {
      type        = "Federated"
      identifiers = [module.project03_eks.oidc_provider_arn]
    }

    # 특정 ServiceAccount만 이 권한 쓸 수 있음
    condition {
      test     = "StringEquals"
      variable = "${replace(module.project03_eks.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }

    # 조건 2: 위에서 작성된 토큰 인증 방식에서 AWS STS를 위한 토큰만 허용
    condition {
      test     = "StringEquals"
      variable = "${replace(module.project03_eks.cluster_oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}


# Role 만들기 (Trust Policy 붙임)
resource "aws_iam_role" "aws_lb_controller" {
  name               = "${module.project03_eks.cluster_name}-aws-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.aws_lb_controller_assume.json
  # ↑ 아까 만든 "누가 쓸 수 있나" 조건서
}

# Role에 권한 카드 붙이기
resource "aws_iam_role_policy_attachment" "aws_lb_controller" {
  role       = aws_iam_role.aws_lb_controller.name
  policy_arn = aws_iam_policy.aws_lb_controller.arn
  # ↑ 아까 GitHub에서 받은 "권한 카드"
}

# ===========================
# 공식 Kubernetes Gateway API CRD 설치
# Terraform이 직접 클러스터에 적용 (local-exec 없음)
# ===========================

# GitHub release에서 Gateway API CRD YAML 다운로드
data "http" "gateway_api_crds_yaml" {
  url = "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.0/standard-install.yaml"
}

# 멀티 도큐먼트 YAML을 개별 manifest로 분리
data "kubectl_file_documents" "gateway_api_crds" {
  content = data.http.gateway_api_crds_yaml.response_body
}

# 각 CRD를 클러스터에 직접 적용
resource "kubectl_manifest" "gateway_api_crds" {
  for_each          = data.kubectl_file_documents.gateway_api_crds.manifests
  yaml_body         = each.value
  server_side_apply = true
  force_conflicts   = true
}

# ===========================
# AWS LBC 전용 Gateway CRD 설치
# ===========================

# LBC Gateway CRD YAML 다운로드
data "http" "lbc_gateway_crds_yaml" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v3.4.0/config/crd/gateway/gateway-crds.yaml"
}

# 멀티 도큐먼트 YAML 파싱
data "kubectl_file_documents" "lbc_gateway_crds" {
  content = data.http.lbc_gateway_crds_yaml.response_body
}

# 각 LBC CRD를 클러스터에 직접 적용
resource "kubectl_manifest" "lbc_gateway_crds" {
  for_each          = data.kubectl_file_documents.lbc_gateway_crds.manifests
  yaml_body         = each.value
  server_side_apply = true
  force_conflicts   = true
  depends_on        = [kubectl_manifest.gateway_api_crds]
}

# ALB Controller를 Helm으로 EKS에 설치
resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "3.4.0" # 최소 2.14.0 이상 필요

  set = [
    { name = "clusterName", value = module.project03_eks.cluster_name },
    { name = "serviceAccount.create", value = "true" },
    { name = "serviceAccount.name", value = "aws-load-balancer-controller" },
    { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn", value = aws_iam_role.aws_lb_controller.arn },
    { name = "controllerConfig.featureGates.ALBGatewayAPI", value = "true" } # enableGatewayAPI 대체
  ]

  depends_on = [
    aws_iam_role_policy_attachment.aws_lb_controller,
    kubectl_manifest.gateway_api_crds,
    kubectl_manifest.lbc_gateway_crds
  ]
}