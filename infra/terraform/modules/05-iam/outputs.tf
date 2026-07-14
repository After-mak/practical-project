# modules/05-iam/outputs.tf

output "eks_cluster_role_arn" {
  description = "EKS 클러스터 IAM 역할 ARN"
  value       = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  description = "EKS 워커 노드 IAM 역할 ARN"
  value       = aws_iam_role.eks_nodes.arn
}
