variable "identifier" {
  description = "RDS instance identifier"
  type        = string
}

variable "engine" {
  description = "DB engine (mysql, postgres 등)"
  type        = string
}

variable "engine_version" {
  description = "DB engine version"
  type        = string
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "allocated_storage" {
  description = "Storage size in GB"
  type        = number
  default     = 20
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = true
}

variable "username" {
  description = "Master DB username"
  type        = string
}

variable "password" {
  description = "Master DB password"
  type        = string
  sensitive   = true
}

variable "db_subnet_group_name" {
  description = "DB subnet group name"
  type        = string
}

variable "vpc_security_group_ids" {
  description = "Security group IDs for RDS"
  type        = list(string)
}

variable "skip_final_snapshot" {
  description = "Skip final snapshot on deletion"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags"
  type        = map(string)
  default     = {}
}

variable "name" {
  type      = string
}

variable "subnet_ids" {
  type      = list(string)
}

