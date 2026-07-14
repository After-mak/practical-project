output "repository_url" {
  description = "생성된 ECR 리포지토리의 URL"
  value = aws_ecr_repository.this.repository_url
}