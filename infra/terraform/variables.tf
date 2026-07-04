# --- AWS 키---
variable "aws_access_key" {
    description = "액세스키"
    type        = string 
}
variable "aws_secret_key" { 
    description = "비밀 액세스키"
    type        = string 
}

variable "aws_profile" {
  type          = string
  description   = "팀원 각자의 AWS CLI 프로필 이름"
}