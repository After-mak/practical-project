############################################
# 1. NETWORK LAYER (VPC / IGW / SUBNET)
############################################

# [1] VPC (Virtual Private Cloud) 생성
# 10.0.0.0/16 대역 생성
module "project03_vpc" {
  source     = "../../modules/01-vpc"
  cidr_block = "10.0.0.0/16"
  name       = "project03-vpc"
}

# [2] 퍼블릭 서브넷 (인터넷 통신 가능 영역) 생성
# Public Subnet A (AZ-a) nat instance가 위치합니다
# EC2 생성 시 자동으로 퍼블릭 IP를 부여함
module "project03_public_subnet_a" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.1.0/24"
  az            = var.azs[0]
  map_public_ip = true 
  name          = "project03-public-subnet-a"
}

# Public Subnet C (AZ-c)
# 고가용성을 유지하기 위해 무조건 2개 이상의 AZ를 요구하므로 만들어둔 서브넷입니다.
module "project03_public_subnet_c" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.2.0/24"
  az            = var.azs[1]
  map_public_ip = true 
  name          = "project03-public-subnet-c"
}


# [3] 프라이빗 서브넷 생성
# Private Subnet (AZ-a)
# az zone a에는 keda와 tailscale 그리고 모니터링에 필요한 grafana, prometheus등이 위치합니다
module "project03_private_subnet_cluster_a" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.10.0/24"
  az            = var.azs[0]
  map_public_ip = false # 외부에서 IP로 직접 접근할 수 없도록 막음
  name          = "project03-private-subnet-cluster-a"
}
# Private Subnet (AZ-a)
# Rds가 위치될 subnet입니다
module "project03_private_subnet_db_a" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.20.0/24"
  az            = var.azs[0]
  map_public_ip = false # 외부에서 IP로 직접 접근할 수 없도록 막음
  name          = "project03-private-subnet-db-a"
}

# Private Subnet (AZ-c)
# worker node들이 배치되어 cluster로 pod들이 돌아갈 private subnet입니다.
module "project03_private_subnet_cluster_c" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.30.0/24"
  az            = var.azs[1]
  map_public_ip = false # 외부에서 IP로 직접 접근할 수 없도록 막음
  name          = "project03-private-subnet-cluster-c"
}

# Private Subnet (AZ-c)
# Rds가 위치될 subnet입니다
module "project03_private_subnet_db_c" {
  source        = "../../modules/02-subnet"
  vpc_id        = module.project03_vpc.vpc_id
  cidr_block    = "10.0.40.0/24"
  az            = var.azs[1]
  map_public_ip = false # 외부에서 IP로 직접 접근할 수 없도록 막음
  name          = "project03-private-subnet-db-c"
}

# [4] Internet Gateway (IGW) 생성
# → 만들어진 VPC가 외부 인터넷과 통신할 수 있도록 출입구(Gateway)를 붙여줍니다.
module "igw" {
  source = "../../modules/03-internet-gateway"
  vpc_id = module.project03_vpc.vpc_id
  name   = "project03-igw"
}



# 변수 ==================
variable "azs" {
  type    = list(string)
  default = ["ap-northeast-2a", "ap-northeast-2c"]
}
# =======================