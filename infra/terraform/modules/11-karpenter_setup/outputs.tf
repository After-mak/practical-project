output "node_iam_role_name" {
  description = "Karpenter 노드가 사용할 IAM Role 이름"
  value       = module.karpenter.node_iam_role_name
}

output "queue_name" {
  description = "Karpenter Spot 중단 알림 SQS 큐 이름"
  value       = module.karpenter.queue_name
}
