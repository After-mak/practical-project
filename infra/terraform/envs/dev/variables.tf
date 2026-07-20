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

variable "elasticache_node_type" {
  description = "Sample FastAPI Redis Queue용 ElastiCache 노드 타입"
  type        = string
  default     = "cache.t3.micro"
}
