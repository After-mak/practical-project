terraform {
  required_providers {
    helm = { source = "hashicorp/helm", version = "~> 2.14" }
  }
}

# ArgoCD 헬름 차트를 설치하기 위한 프로바이더
provider "helm" {
  kubernetes { 
    config_path = "~/.kube/config" 
  }
}