resource "aws_ecr_repository" "this" {
  name = var.repository_name
  image_tag_mutability = var.image_tag_mutability

  # 이미지 푸시 시 취약점 자동 스캔
  image_scanning_configuration {
    scan_on_push = true
  }
}

# 오래된 이미지 자동 삭제
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    "rules": [
        {
            rulePriority = 1,
            description = "Keep last 10 images",
            selection = {
                tagStatus = "any",
                countType = "imageCountMoreThan",
                countNumber = 10
            },
            action = {
                type = "expire"
            }
        }
    ]
  })
}