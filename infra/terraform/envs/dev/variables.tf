variable "aws_profile" {
  description = "AWS CLI 프로필 이름"
  type        = string
  default     = "admin-seonggyu"
}

variable "db_user" {
  description = "RDS 관리자 계정 이름"
  type        = string
}

variable "db_password" {
  description = "RDS 관리자 계정 비밀번호"
  type        = string
  sensitive   = true
}

variable "tailscale_auth_key" {
  description = "Tailscale 인증 키"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "서비스 도메인 이름"
  type        = string
  default     = "tuby.shop"
}

variable "acm_certificate_arn" {
  description = "init에서 발급받은 ACM 인증서 ARN"
  type        = string
  default     = ""
}

variable "telegram_bot_token" {
  description = "모니터링 Alertmanager가 사용할 텔레그램 봇 토큰"
  type        = string
  sensitive   = true
}

variable "telegram_chat_id" {
  description = "모니터링 알림을 받을 텔레그램 chat_id"
  type        = number
  sensitive   = true
}

variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
}
