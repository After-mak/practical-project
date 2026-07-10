# modules/02-subnet/outputs.tf

output "public_subnet_ids" {
  # [*]는 생성된 모든 public 서브넷의 id들을 리스트로 묶어서 반환함  
  description = "public 서브넷 아이디"
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  # EKS용
  description = "private 서브넷 아이디"
  value = aws_subnet.private[*].id
}

output "database_subnet_ids" {
  # RDS용
  description = "database 서브넷 아이디"
  value = aws_subnet.database[*].id
}