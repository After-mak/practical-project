# 1. 도메인의 Hosted Zone 정보 가져오기
data "aws_route53_zone" "this" {
  name         = var.domain_name
  private_zone = false
}

# 2. 도메인을 ALB로 연결하는 Alias(A) 레코드 생성
resource "aws_route53_record" "alb_alias" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = var.alb_dns_name
    zone_id                = var.alb_zone_id
    evaluate_target_health = true
  }
}
