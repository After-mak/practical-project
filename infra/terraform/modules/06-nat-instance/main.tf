data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_instance" "nat" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = var.security_group_ids
  key_name               = var.key_name
  iam_instance_profile   = aws_iam_instance_profile.nat_ssm_profile.name

  # NAT 인스턴스의 핵심: 자신을 목적지로 하지 않는 트래픽도 수신/전송할 수 있도록 허용
  source_dest_check = false

  user_data = <<-EOF
              #!/bin/bash
              # IP 포워딩 활성화
              sysctl -w net.ipv4.ip_forward=1
              echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/custom-ip-forwarding.conf
              
              # iptables 설치 및 구성
              yum install -y iptables-services
              systemctl enable iptables
              systemctl start iptables
              
              # 2. iptables 포워딩 전면 허용 (이 부분이 핵심!)
              iptables -P FORWARD ACCEPT
              iptables -I FORWARD -j ACCEPT
              
              # 3. 마스커레이딩(NAT) 룰 추가 (VPC 내부망 대역 전체를 소스로 지정)
              iptables -t nat -A POSTROUTING -s 10.0.0.0/16 -j MASQUERADE
              
              # 4. MTU 문제 해결을 위한 TCP MSS Clamping 추가 (매우 중요: HTTPS 접속 멈춤 현상 방지)
              iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
              
              iptables-save > /etc/sysconfig/iptables

              # Tailscale 설치 및 Subnet Router 설정
              curl -fsSL https://tailscale.com/install.sh | sh
              systemctl enable --now tailscaled
              
              # Tailscale 인증 및 라우팅 광고 시작
              tailscale up --authkey="${var.tailscale_auth_key}" --advertise-routes=10.0.0.0/16 --hostname="${var.name}"
              EOF

  tags = {
    Name = var.name
    Role = "NAT-Instance"
  }
}

# ---------------------------------------------------------
# [핵심] NAT 인스턴스용 고정 공인 IP (Elastic IP) 생성
# ---------------------------------------------------------
# 일반적인 EC2의 퍼블릭 IP는 컴퓨터를 껐다 켜면 주소가 바뀌어 버립니다.
# NAT 인스턴스는 외부 인터넷으로 나가는 '고정된 출구' 역할을 해야 하므로,
# 절대로 주소가 바뀌지 않는 고정 IP(EIP)를 발급받아야 합니다.
resource "aws_eip" "nat_eip" {
  domain = "vpc"

  tags = {
    Name = "${var.name}-eip"
  }
}

# ---------------------------------------------------------
# 고정 IP(EIP)를 NAT 인스턴스에 연결(결합)
# ---------------------------------------------------------
# 위에서 발급받은 고정 IP(aws_eip.nat_eip)를
# 우리가 만든 NAT 컴퓨터(aws_instance.nat)의 랜선 잭에 찰칵 꽂아주는 작업입니다.
resource "aws_eip_association" "nat_eip_assoc" {
  instance_id   = aws_instance.nat.id
  allocation_id = aws_eip.nat_eip.id
}
# ---------------------------------------------------------
# [SSM 디버깅용 IAM Role 및 Profile 생성]
# ---------------------------------------------------------
resource "aws_iam_role" "nat_ssm_role" {
  name = "${var.name}-ssm-role-${random_id.nat_id.hex}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "random_id" "nat_id" {
  byte_length = 4
}

resource "aws_iam_role_policy_attachment" "nat_ssm_attach" {
  role       = aws_iam_role.nat_ssm_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "nat_ssm_profile" {
  name = "${var.name}-ssm-profile-${random_id.nat_id.hex}"
  role = aws_iam_role.nat_ssm_role.name
}
