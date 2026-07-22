resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis-subnet-group"
  subnet_ids = var.subnet_ids

  tags = merge(
    { Name = "${var.name_prefix}-redis-subnet-group" },
    var.tags
  )
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-redis-sg"
  description = "Allow Redis TLS access from EKS worker nodes"
  vpc_id      = var.vpc_id

  tags = merge(
    { Name = "${var.name_prefix}-redis-sg" },
    var.tags
  )
}

resource "aws_vpc_security_group_ingress_rule" "from_eks_nodes" {
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = var.eks_node_security_group_id
  description                  = "Redis from EKS worker nodes"
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name_prefix}-redis"
  description          = "Redis queue for Sample FastAPI and KEDA validation"

  engine             = "redis"
  node_type          = var.node_type
  port               = 6379
  num_cache_clusters = 1

  automatic_failover_enabled = false
  multi_az_enabled           = false

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"
  apply_immediately          = true

  tags = merge(
    { Name = "${var.name_prefix}-redis" },
    var.tags
  )
}
