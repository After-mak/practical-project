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

# 서비스별 HTTPRoute는 mak-argocd-deploy의 Helm chart가 Argo CD로 관리합니다.
# 동일 오브젝트를 Terraform에 선언하면 Argo CD prune/selfHeal과 소유권이 충돌할 수 있습니다.

# ALB 대기 (이 다음 route53을 달아야되기 때문에 pod에서 요청 넘기고 실제 alb가 생성되기까지 기다리기) 
# The Argo CD application module depends on this guard. During destroy that
# reverses the order and leaves time for HTTPRoutes and target groups to be
# removed before the shared Gateway/ALB disappears.
resource "time_sleep" "wait_for_gateway_cleanup" {
  depends_on       = [kubectl_manifest.gateway]
  destroy_duration = "120s"
}

resource "time_sleep" "wait_for_alb" {
  depends_on      = [kubectl_manifest.gateway]
  create_duration = "300s"
}
# alb arn, host zone id 등 필요한 정보를 얻어내기 위해 data 사용
data "aws_lb" "this" {
  name       = "project03-alb"
  depends_on = [time_sleep.wait_for_alb]

  lifecycle {
    postcondition {
      condition     = self.vpc_id == data.terraform_remote_state.infra.outputs.vpc_id
      error_message = "project03-alb exists in a different VPC. Remove the stale ALB/target groups before provisioning this environment."
    }
  }
}
