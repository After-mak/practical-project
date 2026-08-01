# modules/09-ecr/variables.tf

variable "repository_name" {
  description = "ECR 리포지토리 이름"
  type = string
}

variable "image_tag_mutability" {
  description = "이미지 태그 덮어쓰기 허용 여부"
  type = string
  default = "MUTABLE"
}