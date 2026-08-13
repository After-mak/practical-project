############################################
# 1. IAM Policy for Thanos S3 Access
############################################
resource "aws_iam_policy" "thanos_s3_policy" {
  name        = "project03-thanos-s3-policy"
  description = "IAM Policy for Thanos to access S3 metrics bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::project03-thanos-metrics-83154bf5"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "arn:aws:s3:::project03-thanos-metrics-83154bf5/*"
        ]
      }
    ]
  })
}

############################################
# 2. IRSA (IAM Role for Service Account)
############################################
module "thanos_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "project03-thanos-s3-role"

  oidc_providers = {
    main = {
      provider_arn               = module.project03_eks.oidc_provider_arn
      # Thanos Sidecar와 Thanos Store Gateway가 이 역할을 사용합니다.
      namespace_service_accounts = [
        "prometheus:prometheus-stack-kube-prom-prometheus",
        "prometheus:thanos-store",
        "prometheus:thanos-query",
        "prometheus:thanos-compactor"
      ]
    }
  }

  role_policy_arns = {
    s3_access = aws_iam_policy.thanos_s3_policy.arn
  }
}

output "thanos_irsa_role_arn" {
  description = "IAM Role ARN for Thanos IRSA"
  value       = module.thanos_irsa.iam_role_arn
}
