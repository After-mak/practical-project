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

# 2. NAT 인스턴스 보안 그룹
resource "aws_security_group" "nat" {
  name        = "${var.name}-nat-sg"
  description = "Security group for NAT Instances"
  vpc_id      = var.vpc_id

  # 프라이빗 서브넷(EKS)의 트래픽을 받아서 인터넷으로 쏘기 위해 인바운드 허용
  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.eks_private_subnet_cidrs
  }

  # 인터넷으로 나가는 아웃바운드 전부 허용
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name}-nat-sg"
  }
}

# 3. EKS 워커 노드 보안 그룹
resource "aws_security_group" "eks_nodes" {
  name        = "${var.name}-eks-node-sg"
  description = "Security group for EKS nodes"
  vpc_id      = var.vpc_id

  # 오직 ALB 보안 그룹을 거쳐서 들어오는 트래픽만 EKS 노드로 접속 허용
  ingress {
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.alb.id]
  }

  # EKS 워커 노드들끼리 서로 통신할 수 있도록 내부 통신은 전부 허용 (Node-to-Node)
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  # 아웃바운드 전부 허용
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name}-eks-node-sg"
  }
}

# 4. RDS (데이터베이스) 보안 그룹
resource "aws_security_group" "rds" {
  name        = "${var.name}-rds-sg"
  description = "Security group for RDS"
  vpc_id      = var.vpc_id

  # EKS 프라이빗 서브넷 대역에서만 5432(PostgreSQL) 접근가능하도록
  ingress {
    from_port   = 5432
    to_port     = 5432
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
