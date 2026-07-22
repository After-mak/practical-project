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
variable "elasticache_node_type" {
  description = "Sample FastAPI Redis Queue용 ElastiCache 노드 타입"
  type        = string
  default     = "cache.t3.micro"
}
variable "azs" {
  description = "사용할 가용 영역 목록"
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2c"]
}
