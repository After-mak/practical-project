# ---------------------------------------------------------------
# 파일 위치 : /home/user1/practical-project/infra/terraform/init/Dynamodb.tf
# ---------------------------------------------------------------

# DynamoDB 테이블 생성 - 동시 수정 방지(Lock)용
resource "aws_dynamodb_table" "terraform_lock" {
  name         = "mak-tf-lock"     # 테이블명
  billing_mode = "PAY_PER_REQUEST" # 비용 지불 방식 (요청 개수당 과금하겠다 비용미미)
  hash_key     = "LockID"          # 카테고리명 마음대로 가능(RDBMS의 PK과 유사)
  # 속성을 이용해서
  attribute {
    name = "LockID" # 카테고리의
    type = "S"      # String 타입
  }
  tags = {
    Name = "Terraform State Lock Table"
  }

  lifecycle {
    prevent_destroy = true
  }
}
