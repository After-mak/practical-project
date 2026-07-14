# modules/11-alb/variables.tf

variable "name" {
  description = "ALB 이름 접두사"
  type        = string
}

variable "vpc_id" {
  description = "ALB를 생성할 VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "ALB를 올릴 퍼블릭 서브넷 ID 리스트"
  type        = list(string)
}

variable "alb_sg_id" {
  description = "ALB 보안그룹 ID"
  type        = string
}
