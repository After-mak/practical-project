output "primary_endpoint_address" {
  description = "ElastiCache Redis Primary Endpoint 주소"
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "port" {
  description = "ElastiCache Redis 연결 포트"
  value       = aws_elasticache_replication_group.this.port
}

output "security_group_id" {
  description = "ElastiCache Redis Security Group ID"
  value       = aws_security_group.this.id
}
