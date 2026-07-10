# modules/03-internet-gateway/outputs.tf

output "internet_gateway_id" {
  description = "생성된 Internet Gateway의 ID"
  value       = aws_internet_gateway.this.id
}
