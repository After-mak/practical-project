variable "domain_name" {
  description = "도메인 이름"
  type        = string
  default = "tuby.shop"
}

variable "alb_dns_name" {
  description = "연결할 ALB의 DNS 이름"
  type        = string
}

variable "alb_zone_id" {
  description = "연결할 ALB의 Route53 Hosted Zone ID"
  type        = string
}
