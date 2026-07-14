# modules/11-alb/main.tf

# 1. ALB 생성
resource "aws_lb" "main" {
  name               = "${var.name}-alb"
  internal           = false # true: 내부용, false: 외부용(인터넷)
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]       # ALB가 사용할 보안그룹
  subnets            = var.public_subnet_ids # ALB가 올라갈 위치 (Public 서브넷)

  enable_deletion_protection = false

  tags = {
    Name = "${var.name}-alb"
  }
}

# 2. 타겟 그룹 설정 (트래픽 목적지)
resource "aws_lb_target_group" "app" {
  name     = "${var.name}-tp-app"
  port     = 80
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  # EKS의 Pod IP로 트래픽을 바로 꽂아줌 -> AWS VPC CNI
  target_type = "ip"

  health_check {
    path                = "/" # pod 헬스 체크 경로
    protocol            = "HTTP"
    matcher             = "200" # 200 OK가 떨어져야 정상으로 판단
    interval            = 30    # 30초 마다 검사
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
  tags = {
    Name = "${var.name}-tg-app"
  }
}

# 3. ALB listener
# 80 (http) 포트로 들어오는 트래픽을 타겟 그룹으로 전달
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}