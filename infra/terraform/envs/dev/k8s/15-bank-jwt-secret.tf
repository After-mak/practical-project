# ----------------------------------------------------------------
# Bank of Anthos JWT Secret 외부화
# ----------------------------------------------------------------
# 이 데이터 소스는 Secret 값을 plan/apply 출력에 표시하지 않지만 Terraform state에는
# 민감값이 저장됩니다. State backend 접근 권한과 암호화를 제한해야 합니다.
# AWS Secret JSON에는 jwtRS256.key, jwtRS256.key.pub 두 키가 모두 있어야 합니다.

data "aws_secretsmanager_secret" "bank_jwt" {
  count = var.enable_bank_jwt_rotation ? 1 : 0
  name  = var.bank_jwt_secretsmanager_name
}

data "aws_secretsmanager_secret_version" "bank_jwt" {
  count     = var.enable_bank_jwt_rotation ? 1 : 0
  secret_id = data.aws_secretsmanager_secret.bank_jwt[0].id
}

locals {
  bank_jwt_data = var.enable_bank_jwt_rotation ? jsondecode(data.aws_secretsmanager_secret_version.bank_jwt[0].secret_string) : {}
}

resource "kubectl_manifest" "bank_namespace" {
  for_each = var.enable_bank_jwt_rotation ? toset(["frontend", "backend"]) : toset([])

  yaml_body = yamlencode({
    apiVersion = "v1"
    kind       = "Namespace"
    metadata = {
      name = each.value
    }
  })
}

resource "kubernetes_secret_v1" "bank_jwt" {
  for_each = var.enable_bank_jwt_rotation ? toset(["frontend", "backend"]) : toset([])

  metadata {
    name      = var.bank_jwt_kubernetes_secret_name
    namespace = each.value
    labels = {
      "app.kubernetes.io/part-of"    = "bank-of-anthos"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  data = {
    "jwtRS256.key"     = local.bank_jwt_data["jwtRS256.key"]
    "jwtRS256.key.pub" = local.bank_jwt_data["jwtRS256.key.pub"]
  }

  type = "Opaque"

  lifecycle {
    precondition {
      condition = alltrue([
        contains(keys(local.bank_jwt_data), "jwtRS256.key"),
        contains(keys(local.bank_jwt_data), "jwtRS256.key.pub"),
      ])
      error_message = "Bank JWT Secrets Manager JSON에는 jwtRS256.key와 jwtRS256.key.pub가 모두 필요합니다."
    }
  }

  depends_on = [kubectl_manifest.bank_namespace]
}
