##########################################
# 9. Karpenter 인프라 (IAM & SQS)
##########################################
module "karpenter" {
  source = "../../../modules/11-karpenter_setup"

  cluster_name      = module.project03_eks.cluster_name
  oidc_provider_arn = module.project03_eks.oidc_provider_arn
}
