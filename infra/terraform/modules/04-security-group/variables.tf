# modules/04-security-group/variables.tf

variable "vpc_id" {
  description = "보안 그룹이 생성될 VPC의 ID"
  type        = string
}

variable "name" {
  description = "보안 그룹 명칭 접두사"
  type        = string
}

variable "eks_private_subnet_cidrs" {
  description = "EKS 프라이빗 서브넷의 CIDR 블록 리스트 (RDS 및 NAT 접근 허용 용도)"
  type        = list(string)
}
