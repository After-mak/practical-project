############################################
# 10. ECR (Sample FastAPI API / Worker Image)
############################################

# FastAPI와 Queue Worker는 동일 이미지를 사용하고 실행 명령만 Kubernetes에서 분리합니다.
module "sample_fastapi_ecr" {
  source = "../../modules/09-ecr"

  repository_name      = "sample-fastapi"
  image_tag_mutability = "IMMUTABLE"
}

output "sample_fastapi_ecr_repository_url" {
  description = "Sample FastAPI와 Worker가 함께 사용할 ECR Repository URL"
  value       = module.sample_fastapi_ecr.repository_url
}
