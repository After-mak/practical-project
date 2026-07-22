# ============================================================
# 1. IAM Policy (AWS 공식 정책 다운로드)
# ============================================================
# AWS 공식 정책 문서를 JSON형태로 GitHub에서 다운로드
data "http" "aws_lb_controller_policy" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v${var.lbc_version}/docs/install/iam_policy.json"
}
# 공식 정책 문서를 하나의 권한으로 만들기
resource "aws_iam_policy" "this" {
  name        = "${var.cluster_name}-aws-lb-controller"
  description = "IAM policy for AWS Load Balancer Controller"
  policy      = data.http.aws_lb_controller_policy.response_body
}

# ============================================================
# 2. IRSA (IAM Roles for Service Accounts)
# ============================================================
# pod가 권한을 사용할 수 있게 하는 권한을 담은 증명서 만들기 / 누가 누구한테 권한을 빌릴 것인가가 명시되어있어야함
# [eks cluster 내부에 특정 pod가 aws 의 권한을 빌리기]
data "aws_iam_policy_document" "assume" {
  statement {
    # pod가 권한달라고 할 때 조건이 맞으면 허용해주는 옵션
    effect  = "Allow"
    # 어떤 방식으로 권한을 빌릴 것인가 => pod가 사용하는 JWT token 방식으로 빌림
    actions = ["sts:AssumeRoleWithWebIdentity"]
    #eks cluster가 발급한 token만 신뢰하는 옵션
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # 특정 ServiceAccount만 이 Role 사용 가능
    condition {
      test     = "StringEquals"
      variable = "${replace(var.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account_name}"]
    }

    # AWS STS용 토큰만 허용
    condition {
      test     = "StringEquals"
      variable = "${replace(var.cluster_oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}
# Role 만들기 (github에서 다운받은 내용 사용)
resource "aws_iam_role" "this" {
  name               = "${var.cluster_name}-aws-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}
# Role에 권한 카드 붙이기
resource "aws_iam_role_policy_attachment" "this" {
  role       = aws_iam_role.this.name
  policy_arn = aws_iam_policy.this.arn
}

# ============================================================
# 3. Kubernetes Gateway API CRDs (표준 스펙)
# ============================================================
# GitHub release에서 Gateway API CRD YAML 다운로드
data "http" "gateway_api_crds_yaml" {
  url = "https://github.com/kubernetes-sigs/gateway-api/releases/download/${var.gateway_api_version}/standard-install.yaml"
}

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

# ============================================================
# 4. AWS LBC 전용 Gateway CRDs (AWS 확장)
# ============================================================
data "http" "lbc_gateway_crds_yaml" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v${var.lbc_version}/config/crd/gateway/gateway-crds.yaml"
}

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

# ============================================================
# 5. Helm으로 ALB Controller 설치
# ============================================================
resource "helm_release" "this" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = var.namespace
  version    = var.lbc_version

  set = [
    { name = "clusterName", value = var.cluster_name },
    { name = "serviceAccount.create", value = "true" },
    { name = "serviceAccount.name", value = var.service_account_name },
    { name = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn", value = aws_iam_role.this.arn },
    { name = "controllerConfig.featureGates.ALBGatewayAPI", value = "true" }
  ]

  depends_on = [
    aws_iam_role_policy_attachment.this,
    kubectl_manifest.gateway_api_crds,
    kubectl_manifest.lbc_gateway_crds
  ]
}