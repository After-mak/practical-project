# ECR (Container Registry)
module "ecr" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_ecr"
  image_tag_mutability = "MUTABLE" # 개발 환경이므로 덮어쓰기 허용
}

output "ecr" {
  description = "Mak ECR Repository URL"
  value       = module.ecr.repository_url
}

module "ecr_frontend" {
  source               = "../modules/09-ecr" # 본인의 ECR 모듈 경로에 맞게 수정
  repository_name      = "mak_frontend_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_frontend" {
  description = "Frontend ECR Repository URL"
  value       = module.ecr_frontend.repository_url
}

module "ecr_userservice" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_userservice_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_userservice" {
  description = "UserService ECR Repository URL"
  value       = module.ecr_userservice.repository_url
}

module "ecr_balancereader" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_balancereader_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_balancereader" {
  description = "BalanceReader ECR Repository URL"
  value       = module.ecr_balancereader.repository_url
}

module "ecr_ledgerwriter" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_ledgerwriter_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_ledgerwriter" {
  description = "LedgerWriter ECR Repository URL"
  value       = module.ecr_ledgerwriter.repository_url
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

module "finops_analyzer_ecr" {
  source = "../modules/09-ecr"

  repository_name      = "finops-analyzer"
  image_tag_mutability = "IMMUTABLE"
}

output "finops_analyzer_ecr_repository_url" {
  description = "FinOps Analyzer ECR Repository URL"
  value       = module.finops_analyzer_ecr.repository_url
}


module "tg_gateway_ecr" {
  source               = "../modules/09-ecr"
  repository_name      = "tg-gateway"
  image_tag_mutability = "IMMUTABLE"
}

output "tg_gateway_ecr_repository_url" {
  description = "TG Gateway ECR Repository URL"
  value       = module.tg_gateway_ecr.repository_url
}

module "krr_demo_seed_ecr" {
  source = "../modules/09-ecr"

  repository_name      = "krr-demo-seed"
  image_tag_mutability = "IMMUTABLE"
}

output "krr_demo_seed_ecr_repository_url" {
  description = "KRR 더미 이력 시딩용 initContainer 이미지 ECR Repository URL"
  value       = module.krr_demo_seed_ecr.repository_url
}
