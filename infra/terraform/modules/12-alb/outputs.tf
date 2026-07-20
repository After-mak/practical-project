# modules/11-alb/outputs.tf

output "alb_dns_name" {
  description = "우리가 웹 브라우저에 입력하고 들어갈 ALB의 접속 주소(도메인)"
  value       = aws_lb.main.dns_name
}

output "zone_id" {
  description = "ALB의 호스팅 영역 ID"
  value       = aws_lb.main.zone_id
}

output "target_group_arn" {
  description = "타겟 그룹의 ARN"
  value       = aws_lb_target_group.app.arn
}