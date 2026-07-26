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
  type      = string
  sensitive = true
}

variable "jwt_public_key" {
  description = "jwt_public_key"
  type      = string
  sensitive = true
}