output "vpc_id" {
  description = "VPC ID used to reject stale ALBs from a previous environment"
  value       = module.project03_vpc.vpc_id
}
