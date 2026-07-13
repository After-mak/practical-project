# modules/07-eks/outputs.tf

output "cluster_name" {
    description = "EKS 클러스터 이름"
    value = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  description = "EKS 클러스터 API 서버 접속 주소"
  value = aws_eks_cluster.main.endpoint
}
    
output "cluster_certificate_authority_data" {
  description = "EKS 클러스터와 안전하게 통신하기 위한 인증서 데이터"
  value = aws_eks_cluster.main.certificate_authority[0].data
}