terraform {
  required_providers {
    helm = { source = "hashicorp/helm", version = "~> 3.0" }
  }
}

# 클러스터 정보 동적 조회 (로컬 kubeconfig 의존성 제거)
data "aws_eks_cluster" "cluster" {
  name = "project03-eks"
}

data "aws_eks_cluster_auth" "cluster" {
  name = "project03-eks"
}

# ArgoCD 헬름 차트를 설치하기 위한 프로바이더
provider "helm" {
  kubernetes = {
    host                   = data.aws_eks_cluster.cluster.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--region", "ap-northeast-2", "--cluster-name", data.aws_eks_cluster.cluster.name]
      env = {
        AWS_PROFILE = var.aws_profile
      }
    }
  }
}
