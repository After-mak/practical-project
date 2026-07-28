# ----------------------------------------------------------------
# KRR(finops) 전용 텔레그램 시크릿 자동화
# ----------------------------------------------------------------
# 목적: destroy/apply를 반복하는 dev 환경에서 텔레그램 봇 토큰/챗ID를 매번 손으로
# kubectl patch 하지 않아도 되도록, AWS Secrets Manager에 한 번만 저장해두면
# apply할 때마다(누가 apply하든) 자동으로 K8s Secret이 채워지게 합니다.
#
# 이름을 krr-telegram-secret으로 분리한 이유: finops 차트가 기본으로 만드는
# <fullname>-telegram(=finops-analyzer-telegram, ArgoCD selfHeal이 계속 되돌림)이나
# tg-gateway의 tg-gateway-secret과 겹치지 않게 하기 위함입니다. finops 차트의
# telegram.existingSecret을 이 이름으로 지정해두면(finops/charts/finops/values.yaml)
# 차트가 자체 Secret을 만들지 않아 ArgoCD가 이 Secret을 아예 건드리지 않습니다.
#
# 사전 준비 (한 번만, 본인 AWS 콘솔/CLI에서 직접):
#   aws secretsmanager create-secret \
#     --name project03/krr-telegram \
#     --secret-string '{"TELEGRAM_BOT_TOKEN":"<본인 토큰>","TELEGRAM_CHAT_ID":"<본인 챗ID>"}' \
#     --profile <본인 AWS 프로필>
# 그 다음 envs/dev/k8s/terraform.tfvars에 enable_krr_telegram_secret = true 추가.

data "aws_secretsmanager_secret" "krr_telegram" {
  count = var.enable_krr_telegram_secret ? 1 : 0
  name  = "project03/krr-telegram"
}

data "aws_secretsmanager_secret_version" "krr_telegram" {
  count     = var.enable_krr_telegram_secret ? 1 : 0
  secret_id = data.aws_secretsmanager_secret.krr_telegram[0].id
}

# ArgoCD의 CreateNamespace=true는 finops Application이 sync된 "이후"에야 네임스페이스를
# 만들기 때문에, Terraform이 그 타이밍에 의존하지 않도록 여기서 명시적으로 만들어둡니다.
# 이미 존재해도(ArgoCD가 먼저 만들었어도) 문제없이 그대로 사용됩니다.
resource "kubernetes_namespace" "finops" {
  count = var.enable_krr_telegram_secret ? 1 : 0
  metadata {
    name = "finops"
  }
}

resource "kubernetes_secret" "krr_telegram" {
  count = var.enable_krr_telegram_secret ? 1 : 0

  metadata {
    name      = "krr-telegram-secret"
    namespace = kubernetes_namespace.finops[0].metadata[0].name
  }

  data = {
    TELEGRAM_BOT_TOKEN = jsondecode(data.aws_secretsmanager_secret_version.krr_telegram[0].secret_string)["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID   = jsondecode(data.aws_secretsmanager_secret_version.krr_telegram[0].secret_string)["TELEGRAM_CHAT_ID"]
  }

  type = "Opaque"
}
