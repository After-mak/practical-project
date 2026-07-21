############################################
# 7. ELASTICACHE (Sample FastAPI Redis Queue)
############################################

module "sample_redis" {
  source = "../../modules/17-elasticache"

  name_prefix = "project03-sample"
  vpc_id      = module.project03_vpc.vpc_id
  subnet_ids = [
    module.project03_private_subnet_db_a.subnet_id,
    module.project03_private_subnet_db_c.subnet_id
  ]

  eks_node_security_group_id = module.security_groups.eks_node_sg_id
  node_type                  = var.elasticache_node_type

  tags = {
    Environment = "dev"
    ManagedBy   = "Terraform"
    Service     = "sample-fastapi"
  }
}

output "redis_primary_endpoint" {
  description = "Sample FastAPI가 사용할 ElastiCache Redis Primary Endpoint"
  value       = module.sample_redis.primary_endpoint_address
}

output "redis_port" {
  description = "Sample FastAPI가 사용할 ElastiCache Redis 포트"
  value       = module.sample_redis.port
}

output "redis_security_group_id" {
  description = "ElastiCache Redis Security Group ID"
  value       = module.sample_redis.security_group_id
}
