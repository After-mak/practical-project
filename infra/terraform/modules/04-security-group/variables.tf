variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "ingress_rules" {
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks      = optional(list(string))
    security_groups  = optional(list(string))
    description = optional(string)
  }))
}

variable "egress_rules" {
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks      = optional(list(string))
    security_groups  = optional(list(string))
    description = optional(string)
  }))
}