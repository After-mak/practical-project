############################################
# 8. Route53 (도메인 연결)
############################################
module "route53" {
  source = "../../modules/13-route53"

  domain_name  = var.domain_name
  alb_dns_name = module.alb.alb_dns_name
  alb_zone_id  = module.alb.zone_id
}
