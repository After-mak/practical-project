############################################
# 3. SECURITY GROUP (방화벽 역할)
############################################

# [1] NAT 인스턴스 보안 그룹 (NAT Instance SG)
# 프라이빗 서브넷 안에 있는 서버들이 인터넷(패키지 업데이트 등)으로 
# 나갈 수 있도록 트래픽을 중계해주는 NAT 인스턴스용 방화벽입니다.
module "project03_nat_sg" {
  source = "../../modules/04-security-group"
  name   = "project03-nat-sg"
  vpc_id = module.project03_vpc.vpc_id

  # 인바운드(들어오는 트래픽) 규칙: 프라이빗 내부망(10.0.0.0/16)에서 오는 모든 트래픽을 허용합니다.
  ingress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["10.0.0.0/16", "100.64.0.0/10"]
    },
    {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Temporary SSH access for debugging"
    }
  ]
  # 아웃바운드(나가는 트래픽) 규칙: 어디로든 자유롭게 나갈 수 있도록 허용합니다.
  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all outbound traffic to internet"
    }
  ]
}

# [2] EKS 노드용 Security Group 
module "project03_node_sg" {
  source = "../../modules/04-security-group"
  name   = "project03-eks-node-sg"
  vpc_id = module.project03_vpc.vpc_id

  ingress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["10.0.0.0/16"]
      description = "VPC 내부에 있는 노드간 통신을 위한 RULE"
    },
    {
      from_port       = 443
      to_port         = 443
      protocol        = "tcp"
      security_groups = [module.project03_cluster_sg.sg_id]
      description     = "EKS control plane으로부터 접속을 허용하는 RULE"
    }
  ]

  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all outbound traffic"
    }
  ]
}

# [3] EKS 클러스터(Control Plane)용 Security Group
module "project03_cluster_sg" {
  source = "../../modules/04-security-group"
  name   = "project03-eks-cluster-sg"
  vpc_id = module.project03_vpc.vpc_id

  ingress_rules = [
    {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/16"]
      description = "HTTPS 접속 허용"
    }
  ]

  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all outbound traffic"
    }
  ]
}

# [3] 데이터베이스 보안 그룹 (DB SG)
module "project03_db_sg" {
  source = "../../modules/04-security-group"
  name   = "project03-db-sg"
  vpc_id = module.project03_vpc.vpc_id

  ingress_rules = [
    # 1. cluster에 있는 pod만이 DB(PostgreSQL 기본 포트 5432)에 접근할 수 있도록 제한합니다.
    {
      from_port       = 5432
      to_port         = 5432
      protocol        = "tcp"
      security_groups = [module.project03_was_sg.sg_id]
      description     = "cluster to DB Access"
    },
    # 2. Tailscale 및 내부망을 통한 DB(5432) 접근을 추가로 허용합니다. (개발/디버깅용)
    {
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/16", "100.64.0.0/10"]
      description = "DB Access from Tailscale and Internal VPC"
    },
    # 3. 내부망을 통한 관리자 SSH 접근 허용 (장애 조치 및 세팅 목적)
    {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/16", "100.64.0.0/10"]
      description = "Internal VPC SSH Access (Tailscale or mgmt)"
    }
  ]
  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all outbound traffic"
    }
  ]
}

# [4] 로드밸런서 보안 그룹 (ALB SG)
# → 사용자(인터넷)가 서비스에 최초로 들어오는 관문 역할을 합니다.
module "project03_alb_sg" {
  source = "../../modules/04-security-group"
  name   = "project03-alb-sg"
  vpc_id = module.project03_vpc.vpc_id

  ingress_rules = [
    # 1. 전 세계 어디서든 HTTP(80) 트래픽을 허용합니다.
    {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "HTTP External Traffic"
    },
    # 2. 전 세계 어디서든 HTTPS(443) 트래픽을 허용합니다. (보안 연결)
    {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "HTTPS External Traffic"
    }
  ]
  egress_rules = [
    {
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = ["0.0.0.0/0"]
      description = "Allow all outbound traffic"
    }
  ]
}

