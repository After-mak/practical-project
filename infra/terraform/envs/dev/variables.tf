variable "tailscale_auth_key" {
  type        = string
  description = "tailscale auth key"
}

variable "db_user" {
  type        = string
  description = "rds에 들어갈 db user name"
}

variable "db_password" {
  type        = string
  description = "rds에 들어갈 db password"
}

variable "aws_profile" {
  type        = string
  description = "팀원 각자의 AWS CLI 프로필 이름"
}
