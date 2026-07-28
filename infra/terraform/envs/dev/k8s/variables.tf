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

variable "enable_krr_telegram_secret" {
  description = <<-EOT
    KRR(finops) 전용 텔레그램 봇 토큰/챗ID를 AWS Secrets Manager에서 읽어와
    krr-telegram-secret이라는 K8s Secret으로 자동 생성할지 여부.
    AWS Secrets Manager에 project03/krr-telegram (JSON: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)를
    미리 만들어둔 사람만 true로 켜세요 - 없는 상태에서 켜면 전체 apply가 실패합니다(다른 팀원
    영향 가능). 기본 false.
  EOT
  type        = bool
  default     = false
}