variable "name_prefix" {
  description = "ElastiCache 리소스 이름에 사용할 접두사"
  type        = string
}

variable "vpc_id" {
  description = "ElastiCache 보안 그룹을 생성할 VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "ElastiCache를 배치할 서로 다른 AZ의 Private Subnet ID 목록"
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "ElastiCache subnet group에는 두 개 이상의 Private Subnet이 필요합니다."
  }
}

variable "eks_node_security_group_id" {
  description = "Redis 6379 연결을 허용할 EKS Worker Node Security Group ID"
  type        = string
}

variable "node_type" {
  description = "ElastiCache 노드 타입"
  type        = string
  default     = "cache.t3.micro"
}

variable "tags" {
  description = "ElastiCache 리소스에 추가할 태그"
  type        = map(string)
  default     = {}
}
