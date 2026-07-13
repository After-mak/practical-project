# modules/04-security-group/main.tf

# 1. ALB (퍼블릭 로드밸런서) 보안 그룹
resource "aws_security_group" "alb" {
  name        = "${var.name}-alb-sg"
  description = "Security group for Public ALB"
  vpc_id      = var.vpc_id

  # 외부에서 들어오는 HTTP (80) 허용
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 외부에서 들어오는 HTTPS (443) 허용
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 아웃바운드 전부 허용
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name}-alb-sg"
  }
}

# 2. RDS (데이터베이스) 보안 그룹
resource "aws_security_group" "rds" {
  name        = "${var.name}-rds-sg"
  description = "Security group for RDS"
  vpc_id      = var.vpc_id

  # EKS 프라이빗 서브넷 대역에서만 3306(MySQL) 접근 허용
  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = var.eks_private_subnet_cidrs
  }

  # 아웃바운드 전부 허용
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name}-rds-sg"
  }
}
