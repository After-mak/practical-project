# ===========================
# Gateway api IAM Role
# ===========================

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
data "aws_iam_policy_document" "aws_lb_controller_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [module.project03_eks.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.project03_eks.cluster_oidc_issuer_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(module.project03_eks.cluster_oidc_issuer_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

# Role 만들기
resource "aws_iam_role" "aws_lb_controller" {
  name               = "${module.project03_eks.cluster_name}-aws-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.aws_lb_controller_assume.json
}

# Role에 권한 붙이기
resource "aws_iam_role_policy_attachment" "aws_lb_controller" {
  role       = aws_iam_role.aws_lb_controller.name
  policy_arn = aws_iam_policy.aws_lb_controller.arn
}
