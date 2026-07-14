# modules/07-eks/main.tf

# 1. EKS 클러스터 (control plane)
resource "aws_eks_cluster" "main" {
    name = "${var.name}-cluster"
    version = var.cluster_version

    # EKS IAM (master) 부여
    role_arn = var.eks_cluster_role_arn

    vpc_config {
      # 마스터가 워커노드와 통신하기 위해 연결될 프라이빗 서브넷들
      subnet_ids = var.private_subnet_ids
      security_group_ids = [var.eks_sg_id]
      # API 서버 접근 설정 (퍼블릭 열어둬야 로컬에서 kubectl 명령어 내리기 가능)
      endpoint_private_access = true  # 프라이빗 통신 허용
      endpoint_public_access = true   # 퍼블릭 API 접근 허용
    }
}

# 2. EKS 노드 그룹 (워커 노드)
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.name}-node-group"
  # EKS IAM (worker) 부여
  node_role_arn = var.eks_node_role_arn

  # 워커 노드가 위치할 프라이빗 서브넷들
  subnet_ids = var.private_subnet_ids

  # 인스턴스 사양 및 OS 설정
  instance_types = ["t3.small"]
  ami_type       = "AL2023_x86_64_STANDARD"

  # 오토스케일링 설정 (워커 노드 개수 설정)
  scaling_config {
    desired_size = 2 # 처음 띄울 워커 노드 수
    max_size     = 3 # 자동 스케일링 최대치
    min_size     = 2 # 최소 유지 대수
  }

  # 노드 업데이트 시, 서비스가 죽지않도록 한 번에 1대씩만 교체
  update_config {
    max_unavailable = 1
  }
}