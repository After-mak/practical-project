provider "aws" {
  region  = "ap-northeast-2"
  profile = var.aws_profile
}

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.16"
    }
    helm = {
      source = "hashicorp/helm"
      # modules/15-argocd의 Helm Provider 2.x 구성 문법 및 Lock 파일과 통일합니다.
      version = "~> 2.14"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = "~> 2.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}
