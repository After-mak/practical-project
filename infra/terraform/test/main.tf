# 테스트용 t3 micro 스팟 인스턴스

data "aws_ami" "ubuntu" {
  most_recent = true
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
  owners = ["099720109477"] # Canonical 공식 ID
}

# T3 Micro 스팟 인스턴스 요청
resource "aws_spot_instance_request" "test_spot" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t3.micro"

  # 스팟 인스턴스 설정
  spot_price           = "0.005" # 최대 지불 가능 금액 ($)
  spot_type            = "one-time"
  wait_for_fulfillment = true

  tags = {
    Name = "azas-profile-test-spot"
  }
}