variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
}

variable "jwt_private_key" {
  description = "jwt_private_key"
  type        = string
  sensitive   = true
}

variable "jwt_public_key" {
  description = "jwt_public_key"
  type        = string
  sensitive   = true
}

variable "aws_profile" { type = string }
variable "domain_name" {
  description = "The domain name for the environment"
  type        = string
}

variable "sample_fastapi_image_repository" {
  description = "Sample FastAPI와 Worker가 사용하는 ECR Repository URL"
  type        = string
}

variable "sample_fastapi_redis_host" {
  description = "Sample FastAPI와 Worker가 연결할 ElastiCache Primary Endpoint"
  type        = string
  default     = ""
}

variable "sample_fastapi_redis_port" {
  description = "Sample FastAPI와 Worker가 연결할 ElastiCache Port"
  type        = number
  default     = 6379
}

variable "finops_analyzer_image_repository" {
  description = "FinOps Analyzer가 사용하는 ECR Repository URL"
  type        = string
  default     = ""
}

variable "chronos_model_image_repository" {
  description = "Chronos 예측 서비스가 사용하는 ECR Repository URL"
  type        = string
  default     = ""
}

variable "enable_krr_demo_seed" {
  description = "Prometheus 기동 전 KRR 시연용 더미 이력 데이터를 채우는 initContainer 활성화 여부 (dev/데모 환경 전용, 기본 비활성)"
  type        = bool
  default     = false
}

variable "krr_demo_seed_image" {
  description = "KRR 더미 이력 시딩 initContainer 이미지 (enable_krr_demo_seed=true일 때만 사용)"
  type        = string
  default     = ""
}
