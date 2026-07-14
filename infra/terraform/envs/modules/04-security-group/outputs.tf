# modules/04-security-group/outputs.tf

output "alb_sg_id" {
  description = "ALB 보안 그룹 ID"
  value       = aws_security_group.alb.id
}

output "nat_sg_id" {
  description = "NAT 인스턴스 보안 그룹 ID"
  value       = aws_security_group.nat.id
}

output "eks_node_sg_id" {
  description = "EKS 워커 노드 보안 그룹 ID"
  value       = aws_security_group.eks_nodes.id
}

output "rds_sg_id" {
  description = "RDS 보안 그룹 ID"
  value       = aws_security_group.rds.id
}
