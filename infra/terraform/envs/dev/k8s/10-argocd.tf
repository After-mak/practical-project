# # ############################################
# # # 10. ArgoCD 설치 및 Application 배포 (모니터링 스택 포함)
# # ############################################
# # # 주의: argocd_deploy 모듈은 자체 provider 설정을 갖고 있어 depends_on을 못 씀
# # #      (module.argocd가 ArgoCD 서버를 먼저 설치해야 argocd_deploy의 data source가 정상 동작함)
# # #      실제 apply 시 argocd 모듈부터 먼저 적용하고, 그 다음 argocd_deploy를 적용해야 함
# # #      (예: terraform apply -target=module.argocd 로 먼저 적용 후 전체 apply)
module "argocd" {
  source      = "../../../modules/15-argocd"
  aws_profile = var.aws_profile
}

# ECR은 init Root Module에서 수명주기를 관리하므로 dev에서는 기존 Repository를 조회만 합니다.
data "aws_ecr_repository" "sample_fastapi" {
  name = "sample-fastapi"
}

data "aws_ecr_repository" "finops_analyzer" {
  name = "finops-analyzer"
}

data "aws_ecr_repository" "chronos_model" {
  name = "chronos-model"
}

# enable_krr_demo_seed가 false면 이 ECR repo가 아직 없어도(init 레이어 미적용) apply가
# 막히지 않도록 count로 조건부 조회합니다.
data "aws_ecr_repository" "krr_demo_seed" {
  count = var.enable_krr_demo_seed ? 1 : 0
  name  = "krr-demo-seed"
}

# Infra와 Kubernetes는 Terraform State를 분리하여 관리하므로,
# Infra State에서 ElastiCache 연결 정보를 읽어 Argo CD Helm values에 자동 주입합니다.
data "terraform_remote_state" "infra" {
  backend = "s3"

  config = {
    bucket  = "tfstate-bucket-95ada58e"
    key     = "dev-infra/terraform.tfstate"
    region  = "ap-northeast-2"
    profile = var.aws_profile
  }
}

module "argocd_deploy" {
  source = "../../../modules/16-argocd-deploy"

  aws_profile                      = var.aws_profile
  grafana_admin_password           = var.grafana_admin_password
  domain_name                      = var.domain_name
  sample_fastapi_image_repository  = data.aws_ecr_repository.sample_fastapi.repository_url
  finops_analyzer_image_repository = data.aws_ecr_repository.finops_analyzer.repository_url
  chronos_model_image_repository   = data.aws_ecr_repository.chronos_model.repository_url
  sample_fastapi_redis_host        = data.terraform_remote_state.infra.outputs.redis_primary_endpoint
  sample_fastapi_redis_port        = data.terraform_remote_state.infra.outputs.redis_port

  bank_jwt_secret_name = var.bank_jwt_kubernetes_secret_name

  enable_krr_demo_seed = var.enable_krr_demo_seed
  krr_demo_seed_image  = var.enable_krr_demo_seed ? "${data.aws_ecr_repository.krr_demo_seed[0].repository_url}:latest" : ""

  # Create: Gateway -> cleanup guard -> Argo CD applications.
  # Destroy: Argo CD applications -> cleanup wait -> Gateway.
  depends_on = [
    module.argocd,
    kubectl_manifest.ebs_gp3_storage_class,
    kubernetes_secret_v1.bank_jwt,
    time_sleep.wait_for_gateway_cleanup
  ]
}
