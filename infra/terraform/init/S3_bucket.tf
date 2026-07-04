# ----------------------------------------------------------------
# 파일 위치 : /home/user1/practical-project/infra/terraform/init/S3_bucket.tf
# ----------------------------------------------------------------

# 파일 최상단 — 버전 명시 (main 프로젝트와 aws 버전 통일)
terraform {
  required_version = ">= 1.14.0, < 2.0.0"
  required_providers {
    aws    = { source = "hashicorp/aws",    version = "~> 6.5" }
    random = { source = "hashicorp/random", version = "~> 3.0" }  # random_id 용
  }
}

# S3 버킷 이름용 랜덤 ID 생성
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# S3 버킷 생성 - 상태 파일(.tfstate) 저장용
resource "aws_s3_bucket" "tfstate_bucket" {
  # 고유한 이름을 보장하기 위해 뒤에 랜덤 16진수 접미사를 붙입니다.
  bucket        = "tfstate-bucket-${random_id.bucket_suffix.hex}"
  force_destroy = false # 실수로 상태 파일이 담긴 버킷이 통째로 날아가는 것을 방지

  lifecycle {
    # prevent_destroy = true
  }
}

# S3 버전 관리 활성화 (틀어지거나 유실되었을 때 과거 상태로 복구하기 위해 필수)
resource "aws_s3_bucket_versioning" "tfstate_versioning" {
  bucket    = aws_s3_bucket.tfstate_bucket.id
  versioning_configuration {
    status  = "Enabled"
  }
}

# S3 서버 사이드 암호화 설정 (민감한 인프라 정보 암호화 보호)
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate_crypto" {
  bucket            = aws_s3_bucket.tfstate_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 버킷 정의 아래 — 퍼블릭 접근 전면 차단 (state 버킷이라 필수)
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
