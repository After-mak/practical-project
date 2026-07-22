variable "aws_profile" {
  description = "AWS CLI 프로필 이름"
  type        = string
  default     = "kt_cloud_infra2"
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
}
