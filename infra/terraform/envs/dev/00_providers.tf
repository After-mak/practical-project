provider "aws" {
  region = "ap-northeast-2"
}

terraform {
 
  required_version = ">= 1.10"


  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # terraform 으로 k8s를 사용할 수 있게 버전 명시 
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}