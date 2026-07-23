variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
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
