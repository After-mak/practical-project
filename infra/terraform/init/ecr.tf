# ECR (Container Registry)
module "ecr" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_ecr"
  image_tag_mutability = "MUTABLE" # 개발 환경이므로 덮어쓰기 허용
}

module "sample_fastapi_ecr" {
  source = "../modules/09-ecr"

  repository_name      = "sample-fastapi"
  image_tag_mutability = "IMMUTABLE"
}

output "sample_fastapi_ecr_repository_url" {
  description = "Sample FastAPI ECR Repository URL"
  value       = module.sample_fastapi_ecr.repository_url
}
