module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id                         = var.vpc_id
  subnet_ids                     = var.subnet_ids
  cluster_endpoint_public_access = true

  enable_cluster_creator_admin_permissions = true
  enable_irsa                              = true

  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
  }

  eks_managed_node_groups = {
    default = {
      instance_types         = var.instance_types
      ami_type               = var.ami_type
      min_size               = var.min_size
      max_size               = var.max_size
      desired_size           = var.desired_size
      vpc_security_group_ids = var.node_security_group_ids
    }
  }
}