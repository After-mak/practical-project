# modules/07-eks/variables.tf

variable "name" {
  description = "EKS 클러스터 이름 접두사"
  type = string
}

variable "cluster_version" {
  description = "EKS 쿠버네티스 버전"
  type = string
  default = "1.31"
}

variable "eks_cluster_role_arn" {
    description = "IAM EKS(마스터 역할 ARN)"
    type = string
}

variable "eks_node_role_arn" {
  description = "IAM EKS(워커 노드 ARN)"
  type = string
}

variable "private_subnet_ids" {
    description = "EKS 워커 노드들이 올라갈 프라이빗 서브넷 리스트"
    type = list(string)
}

variable "eks_sg_id" {
    description = "EKS SG"
    type = string
}
