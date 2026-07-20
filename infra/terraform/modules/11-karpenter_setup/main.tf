module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = var.cluster_name

  # Karpenter Controller 파드가 AWS API를 호출할 권한 (IRSA)
  enable_irsa            = true
  irsa_oidc_provider_arn = var.oidc_provider_arn

  # Karpenter가 띄울 EC2 인스턴스가 사용할 IAM Role 생성
  create_node_iam_role = true
  node_iam_role_name   = "karpenter-node-role-${var.cluster_name}"

  # Karpenter 노드들이 EKS 클러스터에 합류할 수 있도록 Access Entry 생성
  create_access_entry = true

  # Spot 인스턴스 중단 알림을 받기 위한 SQS 큐 및 EventBridge 생성
  # v20 모듈부터는 SQS 생성이 기본값(Default: true)으로 켜져 있어서 옵션 생략이 가능합니다.
}
