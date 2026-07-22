# prometheus stack 을 "argocd_application" 으로 배포할 준비를 해 보세요.
resource "argocd_application" "prometheus_stack" {
  # 배포할 app 의 이름과 namespace 를 명시 한다 
  metadata {
    name      = "prometheus-stack"
    namespace = "argocd"
  }
  spec {
    project = "default"
    source {
      # helm repository 주소 또는 github 주소도 가능
      repo_url = "https://prometheus-community.github.io/helm-charts"
      # 설치할 chart 의 이름
      chart = "kube-prometheus-stack"
      # 버전 
      target_revision = "87.10.1"
      # chart 를 설치할때 custom 변수 전달하기
      helm {
        values = templatefile("${path.module}/prometheus/my-values.yaml.tpl", {
          grafana_admin_password = var.grafana_admin_password
        })
      }
    }
    destination {
      # 정해진 이름 
      server    = "https://kubernetes.default.svc"
      namespace = "prometheus" # 배포할 namespace 지정 
    }
    # 동기화 정책
    sync_policy {
      automated {
        prune     = true
        self_heal = true
      }
      # 크기가 크고 무거운 chart 는 ServerSideApply=true 옵션을 같이 전달한다
      # argocd 는 용량 제한이 있기때문에 k8s 에 직접 던져서 실행이 되도록 
      sync_options = ["CreateNamespace=true", "ServerSideApply=true"]
    }
    # 쿠버네티스가 자동으로 주입하는 인증서 값 무시하기 (무한 핑퐁 방지)
    ignore_difference {
      group         = "admissionregistration.k8s.io"
      kind          = "ValidatingWebhookConfiguration"
      name          = "prometheus-stack-kube-prom-admission"
      json_pointers = ["/webhooks/0/clientConfig/caBundle"]
    }

    ignore_difference {
      group         = "admissionregistration.k8s.io"
      kind          = "MutatingWebhookConfiguration"
      name          = "prometheus-stack-kube-prom-admission"
      json_pointers = ["/webhooks/0/clientConfig/caBundle"]
    }
  }
}

resource "argocd_application" "mak-app" {
  metadata {
    name      = "mak-app"
    namespace = "argocd"
  }
  spec {
    project = "default"
    source {
      # 1. 배포용 Git 저장소 주소
      repo_url        = "https://github.com/After-mak/mak-argocd-deploy.git"
      target_revision = "main"

      # 2. Chart.yaml이 들어있는 폴더 경로 지정
      path = "charts/mak-app"
    }

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "default"
    }
    sync_policy {
      automated {
        prune     = true
        self_heal = true # Git 상태와 다르면 K8s 리소스를 자동으로 맞춤
      }
      sync_options = ["CreateNamespace=true"]
    }
  }
}

# EKS가 다시 생성되어도 Argo CD가 GitOps Chart를 읽어 Sample FastAPI와 Worker를 복구합니다.
# 실제 ECR 주소와 ElastiCache Endpoint는 Terraform 결과를 Helm values로 주입합니다.
resource "argocd_application" "sample_fastapi" {
  metadata {
    name      = "sample-fastapi"
    namespace = "argocd"
  }

  spec {
    project = "default"

    source {
      repo_url        = "https://github.com/After-mak/mak-argocd-deploy.git"
      target_revision = "main"
      path            = "charts/sample-fastapi"

      helm {
        values = yamlencode({
          image = {
            repository = var.sample_fastapi_image_repository
            tag        = var.sample_fastapi_image_tag
          }
          redis = {
            host = var.sample_fastapi_redis_host
            port = var.sample_fastapi_redis_port
          }
        })
      }
    }

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "sample-fastapi"
    }

    sync_policy {
      automated {
        prune     = true
        self_heal = true
      }
      sync_options = ["CreateNamespace=true"]
    }
  }
}

resource "argocd_application" "postgres-app" {
  metadata {
    name      = "postgres-app"
    namespace = "argocd"
  }
  spec {
    project = "default"
    source {
      # 1. 일반 Git 저장소 주소
      repo_url        = "https://github.com/After-mak/mak-argocd-deploy.git"
      target_revision = "main"

      # 2. Chart.yaml이 들어있는 폴더 경로 지정
      path = "charts/postgres"
    }

    destination {
      server    = "https://kubernetes.default.svc"
      namespace = "default"
    }
    sync_policy {
      automated {
        prune     = true
        self_heal = true
      }
      sync_options = ["CreateNamespace=true"]
    }
  }
}
