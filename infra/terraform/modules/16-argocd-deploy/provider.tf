terraform {
  required_providers {
    # ArgoCD 전용 프로바이더 선언
    argocd = {
      source  = "oboukili/argocd"
      version = "6.1.1" # 최신 안정화 버전
    }
    # terraform 으로 k8s 자원들을 provision 할수 있도록 provider 추가 
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}
# 클러스터 정보 동적 조회 (로컬 kubeconfig 의존성 제거)
data "aws_eks_cluster" "cluster" {
  name = "project03-eks"
}

data "aws_eks_cluster_auth" "cluster" {
  name = "project03-eks"
}

# 클러스터 접속정보 (context 가 변경되어 있어야 한다 -> 동적 조회로 개선)
provider "kubernetes" {
  host                   = data.aws_eks_cluster.cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.cluster.certificate_authority[0].data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--region", "ap-northeast-2", "--cluster-name", data.aws_eks_cluster.cluster.name]
    env = {
      AWS_PROFILE = var.aws_profile
    }
  }
}

# K8s 안에서 ArgoCD Service 리소스를 검색해서 가져옴
data "kubernetes_service" "argocd_server" {
  metadata {
    name      = "argocd-server" # 헬름이 생성한 서비스 이름
    namespace = "argocd"        # namespace 
  }
}

# ArgoCD API 접속 프로바이더
provider "argocd" {
  # cluster_ip (vpn 연결된 eks 에서 사용할 예정) 대신, 현재 실행 중인 port-forward 이용
  server_addr = "localhost:8080"
  # external_ip
  # server_addr = "${data.kubernetes_service.argocd_server.status[0].load_balancer[0].ingress[0].ip}:80"

  # 초기 로그인 계정 정보
  username = "admin"
  # 설정한 argocd 비밀번호
  password = "@abcd1234"

  # --insecure 로 HTTPS를 껐기 때문에 아래 옵션이 반드시 필요
  plain_text = true
  insecure   = true
}