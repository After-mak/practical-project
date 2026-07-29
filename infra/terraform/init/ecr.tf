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

module "ecr_contacts" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_contacts_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_contacts" {
  description = "Contacts ECR Repository URL"
  value       = module.ecr_contacts.repository_url
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

module "ecr_transactionhistory" {
  source               = "../modules/09-ecr"
  repository_name      = "mak_transactionhistory_ecr"
  image_tag_mutability = "MUTABLE"
}

output "ecr_transactionhistory" {
  description = "TransactionHistory ECR Repository URL"
  value       = module.ecr_transactionhistory.repository_url
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

  repository_name = "krr-demo-seed"
  # latest 태그를 CI가 매번 재푸시해서 덮어써야 하므로 MUTABLE로 설정합니다
  # (IMMUTABLE이면 최초 1회 이후 latest 재푸시가 전부 실패함 - 실제로 겪은 문제).
  image_tag_mutability = "MUTABLE"
}

output "krr_demo_seed_ecr_repository_url" {
  description = "KRR 더미 이력 시딩용 initContainer 이미지 ECR Repository URL"
  value       = module.krr_demo_seed_ecr.repository_url
}

module "chronos_model_ecr" {
  source = "../modules/09-ecr"

  repository_name      = "chronos-model"
  image_tag_mutability = "IMMUTABLE"
}

output "chronos_model_ecr_repository_url" {
  description = "Chronos 선제 오토스케일링 모델 서비스 ECR Repository URL"
  value       = module.chronos_model_ecr.repository_url
}
