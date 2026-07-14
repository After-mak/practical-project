############################################
# 2. ROUTING LAYER (라우팅 테이블)
############################################

# [1] Public Route Table
# 인터넷 게이트웨이(IGW)를 향하는 기본 라우팅(0.0.0.0/0)을 설정합니다.
# 라우팅 테이블에 연결된 서브넷은 외부 인터넷과 직접 통신이 가능합니다.
resource "aws_route_table" "project03_public_rt" {
  vpc_id = module.project03_vpc.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = module.igw.igw_id
  }

  tags = {
    Name = "project03-public-rt"
  }
}

# Public Subnet 연결
# A와 C 두 개의 퍼블릭 서브넷을 위에서 만든 라우팅 테이블에 연결합니다.
resource "aws_route_table_association" "public_a_rt" {
  subnet_id      = module.project03_public_subnet_a.subnet_id
  route_table_id = aws_route_table.project03_public_rt.id
}

resource "aws_route_table_association" "public_c_rt" {
  subnet_id      = module.project03_public_subnet_c.subnet_id
  route_table_id = aws_route_table.project03_public_rt.id
}


# [2] NAT 인스턴스
# 퍼블릭 서브넷 A에 위치하는 NAT instance
module "project03_nat_instance_A" {
  source             = "../../modules/06-nat-instance"
  name               = "project03-nat-instance"
  subnet_id          = module.project03_public_subnet_a.subnet_id
  security_group_ids = [module.security_groups.nat_sg_id]
  tailscale_auth_key = var.tailscale_auth_key
}

# 퍼블릭 서브넷 C에 위치하는 NAT instance
module "project03_nat_instance_C" {
  source             = "../../modules/06-nat-instance"
  name               = "project03-nat-instance"
  subnet_id          = module.project03_public_subnet_c.subnet_id
  security_group_ids = [module.security_groups.nat_sg_id]
  tailscale_auth_key = var.tailscale_auth_key
}


# [3] Private Route Table
# private subnet이 이용하는 라우팅 테이블입니다.
# nat instance를 통해 외부와 연결됩니다
resource "aws_route_table" "project03_private_rt" {
  vpc_id = module.project03_vpc.vpc_id

  route {
    cidr_block = "0.0.0.0/0"
    # NAT 인스턴스의 네트워크 인터페이스 ID를 목적지로 지정
    network_interface_id = module.project03_nat_instance_A.primary_network_interface_id
  }

  depends_on = [module.project03_nat_instance_A]

  tags = {
    Name = "project03-private-rt"
  }
}

# [4] Private Subnet 연결
# cluster로 사용할 서브넷과 DB 서브넷을 프라이빗 라우팅 테이블에 연결합니다.
resource "aws_route_table_association" "cluster_rt_A" {
  subnet_id      = module.project03_private_subnet_cluster_a.subnet_id
  route_table_id = aws_route_table.project03_private_rt.id
}

resource "aws_route_table_association" "db_rt_A" {
  subnet_id      = module.project03_private_subnet_db_a.subnet_id
  route_table_id = aws_route_table.project03_private_rt.id
}

resource "aws_route_table_association" "cluster_rt_C" {
  subnet_id      = module.project03_private_subnet_cluster_c.subnet_id
  route_table_id = aws_route_table.project03_private_rt.id
}

resource "aws_route_table_association" "db_rt_C" {
  subnet_id      = module.project03_private_subnet_db_c.subnet_id
  route_table_id = aws_route_table.project03_private_rt.id
}

