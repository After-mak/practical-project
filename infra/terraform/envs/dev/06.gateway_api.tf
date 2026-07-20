# ===========================
# Gateway api
# ===========================

# terraform 이 helm으로 eks에 설치할 수 있게 정보 알려주는 내용
provider "helm" {
  kubernetes {
    host                   = module.project03_eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.project03_eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.project03_eks.cluster_name]
    }
  }
}

resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"
  version    = "1.7.2"

  set {
    name  = "clusterName"
    value = module.project03_eks.cluster_name
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }


  set {
    name  = "region"
    value = "ap-northeast-2"
  }

  set {
    name  = "vpcId"
    value = module.project03_vpc.vpc_id
  }

  depends_on = [module.project03_eks]
}