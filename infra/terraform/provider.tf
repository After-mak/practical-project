provider "aws" {
  region      = "ap-northeast-2"     # 서울 리전
  profile     = var.aws_profile
  access_key  = var.aws_access_key
  secret_key  = var.aws_secret_key
}
