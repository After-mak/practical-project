variable "aws_profile" {
  description = "AWS CLI 프로필 이름"
  type        = string
  default     = "admin-mingi"
}
variable "domain_name" {
  description = "서비스 도메인 이름"
  type        = string
  default     = "tuby.shop"
}
variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
  default     = "admin1234"

  validation {
    condition     = var.grafana_admin_password == "admin1234"
    error_message = "Grafana admin password is fixed to admin1234 for this project environment."
  }
}

variable "bank_jwt_secretsmanager_name" {
  description = "교체용 Bank of Anthos JWT 키 쌍이 저장된 AWS Secrets Manager 이름"
  type        = string
  default     = "project03/bank-of-anthos/jwt-v2"
}

variable "enable_bank_jwt_rotation" {
  description = "신규 Bank JWT를 Secrets Manager에서 읽어 Kubernetes Secret과 Argo CD 참조를 함께 전환할지 여부"
  type        = bool
  default     = false
}

variable "bank_jwt_current_kubernetes_secret_name" {
  description = "JWT 교체 전 Frontend/Backend가 계속 참조할 기존 Kubernetes Secret 이름"
  type        = string
  default     = "jwt-key"
}

variable "bank_jwt_kubernetes_secret_name" {
  description = "Frontend/Backend가 공통으로 참조할 교체용 Kubernetes Secret 이름"
  type        = string
  default     = "bank-jwt-key-v2"
}

variable "enable_krr_demo_seed" {
  description = "Prometheus 기동 전 KRR 시연용 더미 이력 데이터를 채우는 initContainer 활성화 여부 (dev/데모 환경 전용, 기본 비활성)"
  type        = bool
  default     = false
}

variable "krr_demo_seed_image" {
  description = "KRR 더미 이력 시딩 initContainer 이미지 (ECR: krr-demo-seed). enable_krr_demo_seed=true일 때만 사용"
  type        = string
  default     = ""
}
