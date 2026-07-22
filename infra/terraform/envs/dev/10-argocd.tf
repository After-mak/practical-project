# # ############################################
# # # 10. ArgoCD 설치 및 Application 배포 (모니터링 스택 포함)
# # ############################################
# # # 주의: argocd_deploy 모듈은 자체 provider 설정을 갖고 있어 depends_on을 못 씀
# # #      (module.argocd가 ArgoCD 서버를 먼저 설치해야 argocd_deploy의 data source가 정상 동작함)
# # #      실제 apply 시 argocd 모듈부터 먼저 적용하고, 그 다음 argocd_deploy를 적용해야 함
# # #      (예: terraform apply -target=module.argocd 로 먼저 적용 후 전체 apply)
module "argocd" {
  source      = "../../modules/15-argocd"
  aws_profile = var.aws_profile
}

# ECR은 init Root Module에서 수명주기를 관리하므로 dev에서는 기존 Repository를 조회만 합니다.
data "aws_ecr_repository" "sample_fastapi" {
  name = "sample-fastapi"
}

module "argocd_deploy" {
  source = "../../modules/16-argocd-deploy"

  aws_profile                     = var.aws_profile
  grafana_admin_password          = var.grafana_admin_password
  sample_fastapi_image_repository = data.aws_ecr_repository.sample_fastapi.repository_url
  sample_fastapi_redis_host       = module.sample_redis.primary_endpoint_address
  sample_fastapi_redis_port       = module.sample_redis.port
}
