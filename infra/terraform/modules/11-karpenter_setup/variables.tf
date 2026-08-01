variable "cluster_name" {
  description = "EKS 클러스터 이름"
  type        = string
}

variable "oidc_provider_arn" {
  description = "EKS 클러스터의 OIDC Provider ARN"
  type        = string
}
