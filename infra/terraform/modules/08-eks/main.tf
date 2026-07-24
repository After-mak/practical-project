module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id                         = var.vpc_id
  subnet_ids                     = var.subnet_ids
  cluster_endpoint_public_access = true

  authentication_mode                      = "API_AND_CONFIG_MAP"
  enable_cluster_creator_admin_permissions = false
  enable_irsa                              = true

  cluster_addons = {
    coredns    = { resolve_conflicts_on_create = "OVERWRITE" }
    kube-proxy = { resolve_conflicts_on_create = "OVERWRITE" }
    vpc-cni    = { resolve_conflicts_on_create = "OVERWRITE" }
  }

  eks_managed_node_groups = {
    eks-management-node = {
      name                   = "eks-management-node"
      instance_types         = var.instance_types
      ami_type               = var.ami_type
      min_size               = 2
      max_size               = 3
      desired_size           = 2
      vpc_security_group_ids = var.node_security_group_ids

      labels = {
        role                      = "management"
        "karpenter.sh/controller" = "true"
      }
    }

    eks-worker-node = {
      name                   = "eks-worker-node"
      instance_types         = var.instance_types
      ami_type               = var.ami_type
      min_size               = var.min_size
      max_size               = var.max_size
      desired_size           = var.desired_size
      vpc_security_group_ids = var.node_security_group_ids

      labels = {
        role = "worker"
      }
    }
  }

  access_entries = {
    for arn in var.admin_users : arn => {
      kubernetes_groups = []
      principal_arn     = arn

      policy_associations = {
        cluster_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }
}