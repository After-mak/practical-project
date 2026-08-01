resource "aws_db_instance" "this" {
  identifier     = var.identifier
  engine         = var.engine
  engine_version = var.engine_version

  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage

  multi_az = var.multi_az # 멀티 리전 활성화

  username = var.username
  password = var.password

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = var.vpc_security_group_ids

  skip_final_snapshot = var.skip_final_snapshot

  tags = merge(
    { Name = var.identifier },
    var.tags
  )
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids

  tags = {
    Name = var.name
  }
}