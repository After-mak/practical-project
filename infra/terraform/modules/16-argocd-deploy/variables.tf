variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
}
variable "aws_profile" { type = string }
