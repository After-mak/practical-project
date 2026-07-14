# modules/05-iam/main.tf

# 1. EKS 클러스터(컨트롤 플레인)를 위한 IAM 역할
# EKS 마스터 노드가 AWS 리소스(EC2, 로드밸런서 등)를 제어할 수 있도록 권한을 부여합니다.
resource "aws_iam_role" "eks_cluster" {
  name = "${var.name}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "eks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}


# 2. EKS 워커 노드(EC2)를 위한 IAM 역할
# 실제 파드들이 띄워지는 EC2 인스턴스들이 가져야 할 권한들입니다.
resource "aws_iam_role" "eks_nodes" {
  name = "${var.name}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

# (1) 워커 노드가 EKS 컨트롤 플레인에 등록되고 통신할 수 있게 하는 필수 권한
resource "aws_iam_role_policy_attachment" "eks_worker_node_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

# (2) 파드들에게 VPC의 프라이빗 IP를 할당할 수 있게 해주는 CNI 네트워킹 권한
resource "aws_iam_role_policy_attachment" "eks_cni_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

# (3) ECR에서 컨테이너 이미지를 다운로드 받을 수 있게 해주는 권한
resource "aws_iam_role_policy_attachment" "eks_ecr_read_only" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

# (4) Session Manager(SSM) 권한
# 워커 노드에 SSH 키 없이도 AWS 콘솔에서 안전하게 접속할 수 있게 해줍니다.
resource "aws_iam_role_policy_attachment" "ssm_managed_instance_core" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  role       = aws_iam_role.eks_nodes.name
}
