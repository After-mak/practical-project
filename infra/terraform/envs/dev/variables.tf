variable "aws_profile" {
  description = "AWS CLI 프로필 이름"
  type        = string
  default     = "kt_cloud_infra2"
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
  default     = "vche.cloud"
}
