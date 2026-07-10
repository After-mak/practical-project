# modules/03-internet-gateway/variables.tf

variable "vpc_id" {
  description = "Internet Gateway를 연결할 VPC의 ID"
  type        = string
}

variable "name" {
  description = "Internet Gateway의 이름 (Name 태그)"
  type        = string
}
