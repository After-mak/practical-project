############################################
# 2. IAM Policy for S3 Access
############################################
resource "aws_iam_policy" "cnpg_s3_policy" {
  name        = "project03-cnpg-s3-policy"
  description = "IAM Policy for CNPG to access S3 backup bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::project03-cnpg-backup-07l03u",
          "arn:aws:s3:::project03-cnpg-backup-07l03u/*"
        ]
      }
    ]
  })
}

############################################
# 3. IRSA (IAM Role for Service Account)
############################################
module "cnpg_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "project03-cnpg-s3-role"

  oidc_providers = {
    main = {
      provider_arn               = module.project03_eks.oidc_provider_arn
      namespace_service_accounts = ["default:cnpg-sa","finops:krr-data-db"]
    }
  }

  role_policy_arns = {
    s3_access = aws_iam_policy.cnpg_s3_policy.arn
  }
}
