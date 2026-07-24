############################################
# 1. CNPG Backup S3 Bucket
############################################
resource "aws_s3_bucket" "cnpg_backup" {
  bucket        = "project03-cnpg-backup-${random_string.suffix.result}"
  force_destroy = true
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

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
          aws_s3_bucket.cnpg_backup.arn,
          "${aws_s3_bucket.cnpg_backup.arn}/*"
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
      namespace_service_accounts = ["default:cnpg-sa"]
    }
  }

  role_policy_arns = {
    s3_access = aws_iam_policy.cnpg_s3_policy.arn
  }
}
