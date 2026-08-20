# ----------------------------------------------------------------
# Bank of Anthos Load Generator 테스트 계정 자동화
# ----------------------------------------------------------------
# 실제 계정 정보는 Git/Helm values에 저장하지 않습니다. AWS Secrets Manager에 아래
# JSON 형식으로 한 번 등록한 뒤 enable_bank_loadgen_credentials=true로 apply하면,
# 클러스터를 재생성해도 frontend/bank-loadgen-credentials가 자동으로 복구됩니다.
#
# {
#   "username": "<Bank 테스트 계정>",
#   "password": "<Bank 테스트 비밀번호>",
#   "recipient-account": "<선택: 송금 대상 계좌>"
# }
#
# 주의: Kubernetes Secret 값은 Terraform state에도 저장되므로 state backend의 암호화와
# 접근 권한을 제한해야 합니다.

data "aws_secretsmanager_secret" "bank_loadgen_credentials" {
  count = var.enable_bank_loadgen_credentials ? 1 : 0
  name  = var.bank_loadgen_credentials_secretsmanager_name
}

data "aws_secretsmanager_secret_version" "bank_loadgen_credentials" {
  count     = var.enable_bank_loadgen_credentials ? 1 : 0
  secret_id = data.aws_secretsmanager_secret.bank_loadgen_credentials[0].id
}

locals {
  bank_loadgen_credentials = var.enable_bank_loadgen_credentials ? jsondecode(
    data.aws_secretsmanager_secret_version.bank_loadgen_credentials[0].secret_string
  ) : {}

  bank_loadgen_username = tostring(lookup(local.bank_loadgen_credentials, "username", ""))
  bank_loadgen_password = tostring(lookup(local.bank_loadgen_credentials, "password", ""))
  bank_loadgen_recipient_account = tostring(
    lookup(local.bank_loadgen_credentials, "recipient-account", "")
  )
}

resource "kubernetes_secret_v1" "bank_loadgen_credentials" {
  count = var.enable_bank_loadgen_credentials ? 1 : 0

  metadata {
    name      = "bank-loadgen-credentials"
    namespace = kubernetes_namespace_v1.bank["frontend"].metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "bank-loadgen"
      "app.kubernetes.io/part-of"    = "bank-of-anthos"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  data = merge(
    {
      username = local.bank_loadgen_username
      password = local.bank_loadgen_password
    },
    local.bank_loadgen_recipient_account != "" ? {
      "recipient-account" = local.bank_loadgen_recipient_account
    } : {}
  )

  type = "Opaque"

  lifecycle {
    precondition {
      condition = alltrue([
        trimspace(local.bank_loadgen_username) != "",
        trimspace(local.bank_loadgen_password) != "",
      ])
      error_message = "Bank Load Generator Secrets Manager JSON에는 비어 있지 않은 username과 password가 필요합니다."
    }
  }
}
