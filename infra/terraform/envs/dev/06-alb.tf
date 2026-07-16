
############################################
# 6. ALB (Public Load Balancer)
############################################
module "alb" {
  source = "../../modules/12-alb"

  name   = "project03"
  vpc_id = module.project03_vpc.vpc_id
  public_subnet_ids = [
    module.project03_public_subnet_a.subnet_id,
    module.project03_public_subnet_c.subnet_id
  ]
  alb_sg_id           = module.security_groups.alb_sg_id
  acm_certificate_arn = var.acm_certificate_arn
}