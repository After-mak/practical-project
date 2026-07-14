# modules/02-subnet/main.tf

resource "aws_subnet" "public" {
    count = length(var.public_subnets) # 리스트에 들어있는 만큼 반복해서 생성 (az가 두개니깐 리스트로 받게함)

    vpc_id = var.vpc_id
    
    cidr_block = var.public_subnets[count.index] # 리스트에서 하나씩 꺼내 쓰기
    tags = {
        name = "public-subnet-${count.index + 1}"
        "kubernetes.io/role/elb" = "1" # ALB 배정을 위함
    }

}
