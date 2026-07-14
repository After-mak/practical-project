############################################
# 3. SECURITY GROUP & IAM
############################################

module "security_groups" {
  source = "../../modules/04-security-group"

  name   = "project03"
  vpc_id = module.project03_vpc.vpc_id

  # 프라이빗 서브넷들의 대역폭
  eks_private_subnet_cidrs = [
    "10.0.10.0/24",
    "10.0.30.0/24",
    "10.0.20.0/24",
    "10.0.40.0/24"
  ]
}

module "iam" {
  source = "../../modules/05-iam"
  name   = "project03"
}
