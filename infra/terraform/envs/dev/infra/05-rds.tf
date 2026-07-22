# ================================
# 5. RDS(생성과 관련 설정을 작성합니다.)
# ================================

resource "aws_db_instance" "this" {
  identifier             = "project03-db"
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t3.small"
  allocated_storage      = 20
  multi_az               = false
  username               = var.db_user
  password               = var.db_password
  vpc_security_group_ids = [module.security_groups.rds_sg_id]
  db_subnet_group_name   = aws_db_subnet_group.this.name

  skip_final_snapshot = true # ← 삭제 시 스냅샷 안 찍음 (개발용)
  tags = {
    Name = "project3-db"
  }
}








# RDS를 사용하기 위한 subnet group 생성
resource "aws_db_subnet_group" "this" {
  name = "project03-db-subnet-group"
  subnet_ids = [
    module.project03_private_subnet_db_a.subnet_id,
    module.project03_private_subnet_db_c.subnet_id
  ]

  tags = {
    Name = "project03-db-subnet-group"
  }
}