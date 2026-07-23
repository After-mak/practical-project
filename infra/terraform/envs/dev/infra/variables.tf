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

variable "eks_admin_users" {
  description = "EKS 클러스터 관리자 권한을 부여할 IAM 사용자 ARN 목록"
  type        = list(string)
  default = [
    "arn:aws:iam::372666940978:user/admin-jongwon",
    "arn:aws:iam::372666940978:user/admin-mingyu",
    "arn:aws:iam::372666940978:user/admin-mingi",
    "arn:aws:iam::372666940978:user/admin-seonggyu",
    "arn:aws:iam::372666940978:user/admin-yeongsik",
    "arn:aws:iam::372666940978:user/admin-sangwoo",
    "arn:aws:iam::372666940978:user/admin-yunseong"
  ]
}
