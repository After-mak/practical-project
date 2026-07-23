##########################################
# 9. Karpenter 인프라 (IAM & SQS)
##########################################
module "karpenter" {
  source = "../../../modules/11-karpenter_setup"

  cluster_name      = module.project03_eks.cluster_name
  oidc_provider_arn = module.project03_eks.oidc_provider_arn
}
resource "helm_release" "karpenter" {
  namespace           = "kube-system"
  name                = "karpenter"
  repository          = "oci://public.ecr.aws/karpenter"
  chart               = "karpenter"
  version             = "1.14.0"
  
  set {
    name  = "settings.clusterName"
    value = module.project03_eks.cluster_name
  }
  
  set {
    name  = "settings.interruptionQueue"
    value = module.karpenter.queue_name
  }
  
  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.karpenter.iam_role_arn
  }

  # Karpenter 파드를 어느 노드에 띄울지 지정
  set {
    name  = "controller.nodeSelector.karpenter\\.sh/controller"
    value = "true"
  }
  # Service account 이름 karpenter 고정
  set {
    name  = "serviceAccount.name"
    value = "karpenter" 
  }
  depends_on = [module.karpenter, module.project03_eks]
}