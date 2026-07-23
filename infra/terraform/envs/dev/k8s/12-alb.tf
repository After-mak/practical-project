# ############################################
# # 6. ALB (Public Load Balancer)
# ############################################


data "aws_acm_certificate" "this" {
  domain   = var.domain_name
  statuses = ["ISSUED"]
}
# CRD/컨트롤러 이후 기본 세팅 =================
resource "kubectl_manifest" "gatewayclass" {
  yaml_body  = file("${path.module}/gateway_api/gatewayclass.yaml")
  depends_on = [kubectl_manifest.gateway_api_crds, helm_release.aws_lb_controller]
}

resource "kubectl_manifest" "lb_config" {
  yaml_body = templatefile("${path.module}/gateway_api/loadbalancerconfigure.yaml", {
    certificate_arn = data.aws_acm_certificate.this.arn
  })
  depends_on = [kubectl_manifest.lbc_gateway_crds, helm_release.aws_lb_controller]
}
# gateway 생성 => alb 생성 ===================
resource "kubectl_manifest" "gateway" {
  yaml_body  = file("${path.module}/gateway_api/gateway.yaml")
  depends_on = [kubectl_manifest.gatewayclass, kubectl_manifest.lb_config]
}


# ALB 대기 (이 다음 route53을 달아야되기 때문에 pod에서 요청 넘기고 실제 alb가 생성되기까지 기다리기) 
resource "time_sleep" "wait_for_alb" {
  depends_on      = [kubectl_manifest.gateway]
  create_duration = "300s"
}
# alb arn, host zone id 등 필요한 정보를 얻어내기 위해 data 사용
data "aws_lb" "this" {
  name       = "project03-alb"
  depends_on = [time_sleep.wait_for_alb]
}
