# ECR (Container Registry)
module "ecr" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_ecr"
  image_tag_mutability = "MUTABLE" # 개발 환경이므로 덮어쓰기 허용
}
