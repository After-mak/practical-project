variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "cluster_version" {
  description = "Kubernetes version"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for EKS"
  type        = list(string)
}

variable "node_security_group_ids" {
  description = "Additional security group IDs for worker nodes"
  type        = list(string)
  default     = []
}

variable "instance_types" {
  description = "EC2 instance types for node group"
  type        = list(string)
}

variable "ami_type" {
  description = "AMI type for node group"
  type        = string
}

variable "min_size" {
  description = "Minimum number of nodes"
  type        = number
}

variable "max_size" {
  description = "Maximum number of nodes"
  type        = number
}

variable "desired_size" {
  description = "Desired number of nodes"
  type        = number
}

variable "admin_users" {
  description = "List of IAM user ARNs to grant cluster admin access"
  type        = list(string)
  default     = []
}