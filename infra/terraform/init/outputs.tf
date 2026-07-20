# DynamoDB 테이블 이름: mak-tf-lock
output "dynamodb_table_name" {
  value       = aws_dynamodb_table.terraform_lock.name
  description = "동시 실행 방지 DynamoDB 테이블 이름"
}

# S3 버킷 이름
output "s3_bucket_name" {
  value       = aws_s3_bucket.tfstate_bucket.id
  description = "상태 파일 저장될 S3 버킷의 이름"
}

# ACM 인증서
output "acm_certificate_arn" {
  value       = aws_acm_certificate.this.arn
  description = "발급된 ACM 인증서 ARN"
}