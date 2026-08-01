# ----------------------------------------------------------------
# KRR(finops) 전용 텔레그램 시크릿 자동화
# ----------------------------------------------------------------
# 목적: destroy/apply를 반복하는 dev 환경에서 텔레그램 봇 토큰/챗ID를 매번 손으로
# kubectl patch 하지 않아도 되도록, AWS Secrets Manager에서 항상 값을 읽어와
# apply할 때마다(누가 apply하든) 자동으로 K8s Secret이 채워지게 합니다.
#
# 이름을 krr-telegram-secret으로 분리한 이유: finops 차트가 기본으로 만드는
# <fullname>-telegram(=finops-analyzer-telegram, ArgoCD selfHeal이 계속 되돌림)이나
# tg-gateway의 tg-gateway-secret과 겹치지 않게 하기 위함입니다. finops 차트의
# telegram.existingSecret을 이 이름으로 지정해두면(finops/charts/finops/values.yaml)
# 차트가 자체 Secret을 만들지 않아 ArgoCD가 이 Secret을 아예 건드리지 않습니다.
#
# 주의: 아래 데이터 소스가 항상 조회되므로, project03/krr-telegram이 AWS Secrets
# Manager에 미리 존재해야 dev-k8s 전체 apply가 됩니다(없으면 이 레이어 apply 자체가
# 실패). 인프라 존재 여부와 무관하게 지금 바로 만들어두면 됩니다:
#   aws secretsmanager create-secret \
#     --name project03/krr-telegram \
#     --secret-string '{"TELEGRAM_BOT_TOKEN":"<본인 토큰>","TELEGRAM_CHAT_ID":"<본인 챗ID>"}' \
#     --profile <본인 AWS 프로필>

data "aws_secretsmanager_secret" "krr_telegram" {
  name = "project03/krr-telegram"
}

data "aws_secretsmanager_secret_version" "krr_telegram" {
  secret_id = data.aws_secretsmanager_secret.krr_telegram.id
}

# ArgoCD의 CreateNamespace=true는 finops Application이 sync된 "이후"에야 네임스페이스를
# 만들기 때문에, Terraform이 그 타이밍에 의존하지 않도록 여기서 명시적으로 만들어둡니다.
# 이미 존재해도(ArgoCD가 먼저 만들었어도) 문제없이 그대로 사용됩니다.
resource "kubernetes_namespace" "finops" {
  metadata {
    name = "finops"
  }
}

resource "kubernetes_secret" "krr_telegram" {
  metadata {
    name      = "krr-telegram-secret"
    namespace = kubernetes_namespace.finops.metadata[0].name
  }

  data = {
    TELEGRAM_BOT_TOKEN = jsondecode(data.aws_secretsmanager_secret_version.krr_telegram.secret_string)["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID   = jsondecode(data.aws_secretsmanager_secret_version.krr_telegram.secret_string)["TELEGRAM_CHAT_ID"]
  }

  type = "Opaque"
}
