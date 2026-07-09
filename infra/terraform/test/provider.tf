terraform {
  required_version = ">= 1.14.0, < 2.0.0"
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
  }
  # terraform 상태 관리를 위한 remote 백엔드 설정, S3 이름은 backend.hcl에 명시
  backend "s3" {
    key             = "infra/terraform.tfstate"   # /infra/하위에 만들어 지도록
    region          = "ap-northeast-2"
    dynamodb_table  = "mak-tf-lock"               # dynamodb 테이블의 이름을 명시하면 lock 상태가 자동으로 관리된다.
    encrypt         = true                        # tfstate에 민감한 정보 암호화
  }
}

provider "aws" {
  region      = "ap-northeast-2"     # 서울 리전
  profile     = var.aws_profile
}
