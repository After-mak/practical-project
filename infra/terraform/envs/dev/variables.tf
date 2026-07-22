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
<<<<<<< HEAD
  default     = "vche.cloud"
=======
  default     = "tuby.shop"
}
variable "acm_certificate_arn" {
  description = "init에서 발급받은 ACM 인증서 ARN"
  type        = string
  default     = ""
>>>>>>> 3d2e2c9ff58ae71b576e2442af0375851dc88fa5
}
variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
}

variable "elasticache_node_type" {
  description = "Sample FastAPI Redis Queue용 ElastiCache 노드 타입"
  type        = string
  default     = "cache.t3.micro"
}
