############################################
# 4. EKS (Control Plane, Worker Node 생성 및 설정)
############################################
module "project03_eks" {
  source = "../../modules/08-eks"

  cluster_name    = "project03-eks"
  cluster_version = "1.32"
  vpc_id          = module.project03_vpc.vpc_id
  subnet_ids = [
    module.project03_private_subnet_cluster_a.subnet_id,
    module.project03_private_subnet_cluster_c.subnet_id
  ]

  node_security_group_ids = [module.security_groups.eks_node_sg_id]

  instance_types = ["t3.small"] # 프리티어 제한
  ami_type       = "AL2023_x86_64_STANDARD"
  min_size       = 2
  max_size       = 3
  desired_size   = 2
}

# eks 접속용 인증 토큰 가져오기
data "aws_eks_cluster_auth" "cluster" {
  name = module.project03_eks.cluster_name
}

provider "kubernetes" {
  host                   = module.project03_eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.project03_eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--region", "ap-northeast-2", "--cluster-name", module.project03_eks.cluster_name]
    env = {
      AWS_PROFILE = var.aws_profile
    }
  }
}
