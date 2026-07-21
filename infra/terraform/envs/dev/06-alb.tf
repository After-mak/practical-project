# ############################################
# # 6. ALB (Public Load Balancer)
# ############################################
resource "kubectl_manifest" "gatewayclass" {
  yaml_body  = file("${path.module}/gateway_api/gatewayclass.yaml")
  depends_on = [null_resource.gateway_api_crds, helm_release.aws_lb_controller]
}

resource "kubectl_manifest" "lb_config" {
  yaml_body  = file("${path.module}/gateway_api/loadbalancerconfigure.yaml")
  depends_on = [null_resource.lbc_gateway_crds, helm_release.aws_lb_controller]
}

resource "kubectl_manifest" "target_group_config" {
  yaml_body  = file("${path.module}/gateway_api/targetgroupconfigure.yaml")
  depends_on = [null_resource.lbc_gateway_crds, kubectl_manifest.service]
}

resource "kubectl_manifest" "gateway" {
  yaml_body  = file("${path.module}/gateway_api/gateway.yaml")
  depends_on = [kubectl_manifest.gatewayclass, kubectl_manifest.lb_config]
}

resource "kubectl_manifest" "route" {
  yaml_body  = file("${path.module}/gateway_api/route.yaml")
  depends_on = [kubectl_manifest.gateway,
                kubectl_manifest.service,
                kubectl_manifest.target_group_config]
}
resource "kubectl_manifest" "service" {
  yaml_body  = file("${path.module}/gateway_api/service.yaml")
  depends_on = [kubectl_manifest.gateway,kubectl_manifest.deploy]
}
resource "kubectl_manifest" "deploy" {
  yaml_body  = file("${path.module}/gateway_api/deploy.yaml")
  depends_on = [kubectl_manifest.gateway]
}

# ALB 대기
resource "null_resource" "wait_for_alb" {
  triggers = {
    gateway_id = kubectl_manifest.gateway.id
  }
  
  provisioner "local-exec" {
    command = <<-EOT
      for i in $(seq 1 30); do
        STATUS=$(aws elbv2 describe-load-balancers \
          --names "project03-alb" \
          --region ap-northeast-2 \
          --query "LoadBalancers[0].State.Code" \
          --output text 2>/dev/null || echo "notfound")
        if [ "$STATUS" = "active" ]; then exit 0; fi
        sleep 10
      done
      exit 1
    EOT
  }
}

data "aws_lb" "this" {
  name       = "project03-alb"
  depends_on = [null_resource.wait_for_alb]
}