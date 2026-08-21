# Prometheus/Grafana/Alertmanager 커스텀 설정
# 담당: 한윤성 (FinOps/모니터링 파트)
alertmanager:
  alertmanagerSpec:
    resources:
      requests:
        cpu: 50m
        memory: 128Mi
      limits:
        cpu: 100m
        memory: 256Mi
  config:
    global:
      resolve_timeout: 5m
    route:
      receiver: 'null'
      group_by: ['alertname']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      routes:
        - receiver: 'tg-gateway-webhook'
          matchers:
            - namespace = "default"
    receivers:
      - name: 'null'
      - name: 'tg-gateway-webhook'
        webhook_configs:
          # TODO: tg-gateway Service의 정확한 이름/네임스페이스는 mak-argocd-deploy 매니페스트 확인 후 확정 필요 (임종원님 확인 필요)
          - url: 'http://tg-gateway-service.default.svc.cluster.local:8000/webhook/alertmanager'
            send_resolved: true
prometheus:
  # Prometheus가 사용할 ServiceAccount에 Thanos S3 IRSA 권한 추가
  serviceAccount:
    create: true
    name: prometheus-stack-kube-prom-prometheus
    annotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::372666940978:role/project03-thanos-s3-role"
  prometheusSpec:
    # Helm release name에 의존하지 않고 명시적인 라벨로 ServiceMonitor를 선택합니다.
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorSelector: {}
    serviceMonitorNamespaceSelector: {}
    # 승인된 k6 Job이 내부 /api/v1/write로 성능 지표를 전송할 수 있게 합니다.
    enableRemoteWriteReceiver: true
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 500m
        memory: 1Gi
    retention: 2d
    thanos:
      objectStorageConfig:
        existingSecret:
          name: thanos-objstore-config
          key: objstore.yml
%{ if enable_krr_demo_seed ~}
    # KRR/Chronos 더미 이력 데이터를 Prometheus가 뜨기 전에 미리 채워 넣는 initContainer입니다.
    # sample-fastapi 네임스페이스뿐 아니라 Bank of Anthos 백엔드(backend 네임스페이스:
    # userservice/contacts/balancereader/ledgerwriter/transactionhistory)까지 함께 시딩합니다.
    # destroy/apply를 반복하는 dev 환경 특성상 "데이터를 보존"하는 대신, Prometheus가
    # 새로 뜰 때마다 그 시점의 실제 파드 이름을 조회해서 매번 새로 만드는 방식입니다.
    # (finops/scripts/generate_krr_dummy_history.py, seed_init_entrypoint.sh 참고)
    # 볼륨 이름은 Prometheus Operator가 자동 생성하는 데이터 볼륨(prometheus-<프로메테우스
    # 리소스 이름>-db)과 반드시 일치해야 합니다 - 현재 배포 기준 실측값이며, Helm release
    # 이름이 바뀌면 같이 바뀌므로 dev-k8s apply 후 실제 이름과 다르면 여기도 갱신 필요합니다.
    initContainers:
      - name: krr-demo-seed
        image: "${krr_demo_seed_image}"
        env:
          - name: SEED_DAYS
            value: "2"
        volumeMounts:
          - name: prometheus-prometheus-stack-kube-prom-prometheus-db
            mountPath: /prometheus
%{ endif ~}
grafana:
  # persistence가 ReadWriteOnce PVC라 기본 RollingUpdate 전략(새 파드를 먼저 띄우고
  # 옛 파드를 나중에 지움)과 근본적으로 충돌합니다 - 새 파드가 볼륨을 못 붙잡아
  # Multi-Attach 에러로 영원히 Pending 상태가 되고, ArgoCD도 그 Deployment가
  # Healthy해지길 기다리다 동기화 자체가 멈춥니다. Recreate로 바꿔서 옛 파드를
  # 먼저 내리고 나서 새 파드를 띄우게 합니다.
  strategy:
    type: Recreate
  # Reflector가 krr-data-db-app Secret(finops)을 이 네임스페이스(prometheus)로
  # 복제해준 것을 env var로 주입합니다. CNPG가 비밀번호를 재발급해도 Reflector가
  # 복제본을 계속 갱신하므로, 여기서는 항상 최신 값을 읽게 됩니다.
  envValueFrom:
    KRR_DB_USER:
      secretKeyRef:
        name: krr-data-db-app
        key: username
    KRR_DB_PASSWORD:
      secretKeyRef:
        name: krr-data-db-app
        key: password
  # KRR-Logs(postgres) 데이터소스는 여기(additionalDataSources)로 등록하지 않습니다.
  # kube-prometheus-stack의 grafana 서브차트가 jsonData의 일부 키(sslmode 등)만
  # 통과시키고 database 같은 나머지 키를 누락시키는 문제가 있어서(재현 확인함),
  # 대신 charts/grafana-finops-dashboard/templates/krr-datasource-configmap.yaml에서
  # grafana_datasource=1 라벨 붙은 ConfigMap으로 직접 등록합니다 (대시보드와 같은 패턴).
  additionalDataSources:
    - name: Thanos
      type: prometheus
      url: http://thanos-query.prometheus.svc.cluster.local:9090
      access: proxy
      isDefault: false
      version: 1
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      searchNamespace: ALL
      folderAnnotation: grafana_folder
      provider:
        foldersFromFilesStructure: true
  persistence:
    enabled: true
    type: pvc
    storageClassName: ebs-gp3
    accessModes:
      - ReadWriteOnce
    size: 5Gi
    finalizers:
      - kubernetes.io/pvc-protection
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  readinessProbe:
    timeoutSeconds: 5
    periodSeconds: 10
    failureThreshold: 6
  livenessProbe:
    timeoutSeconds: 5
    periodSeconds: 10
    failureThreshold: 6
  adminPassword: "${grafana_admin_password}"
  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
        - name: 'finops-dashboards'
          orgId: 1
          folder: 'FinOps'
          type: file
          disableDeletion: false
          editable: true
          options:
            path: /var/lib/grafana/dashboards/finops-dashboards
  dashboards:
    finops-dashboards:
      finops-overview:
        json: |
          {
            "title": "FinOps Overview",
            "uid": "finops-overview",
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "refresh": "30s",
            "time": { "from": "now-1h", "to": "now" },
            "panels": [
              {
                "id": 1,
                "title": "Pod CPU Usage (cores)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "targets": [
                  {
                    "expr": "sum(rate(container_cpu_usage_seconds_total{namespace!=\"kube-system\", container!=\"\", container!=\"POD\"}[5m])) by (pod)",
                    "legendFormat": "{{pod}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 2,
                "title": "HPA Current vs Desired Replicas",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "targets": [
                  {
                    "expr": "kube_horizontalpodautoscaler_status_current_replicas",
                    "legendFormat": "current - {{horizontalpodautoscaler}}",
                    "refId": "A"
                  },
                  {
                    "expr": "kube_horizontalpodautoscaler_status_desired_replicas",
                    "legendFormat": "desired - {{horizontalpodautoscaler}}",
                    "refId": "B"
                  }
                ]
              },
              {
                "id": 3,
                "title": "Pod Restart Count",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 24, "x": 0, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "targets": [
                  {
                    "expr": "sum(kube_pod_container_status_restarts_total{namespace!=\"kube-system\"}) by (pod)",
                    "legendFormat": "{{pod}}",
                    "refId": "A"
                  }
                ]
              }
            ],
            "templating": {
              "list": [
                {
                  "name": "datasource",
                  "type": "datasource",
                  "query": "prometheus",
                  "current": {}
                }
              ]
            }
          }
      sample-fastapi-workload:
        json: |
          {
            "title": "Sample FastAPI Workload",
            "uid": "sample-fastapi-workload",
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "refresh": "10s",
            "time": { "from": "now-30m", "to": "now" },
            "tags": ["finops", "sample-fastapi", "keda"],
            "panels": [
              {
                "id": 1,
                "title": "Redis Queue State",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "short", "min": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "max(sample_queue_length{namespace=\"sample-fastapi\",service=\"sample-fastapi\"}) or vector(0)",
                    "legendFormat": "pending",
                    "refId": "A"
                  },
                  {
                    "expr": "max(sample_queue_processing_length{namespace=\"sample-fastapi\",service=\"sample-fastapi\"}) or vector(0)",
                    "legendFormat": "processing",
                    "refId": "B"
                  },
                  {
                    "expr": "max(sample_queue_dead_letter_length{namespace=\"sample-fastapi\",service=\"sample-fastapi\"}) or vector(0)",
                    "legendFormat": "dead-letter",
                    "refId": "C"
                  }
                ]
              },
              {
                "id": 2,
                "title": "Worker Deployment Replicas",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "short", "min": 0, "decimals": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "kube_deployment_status_replicas{namespace=\"sample-fastapi\",deployment=\"sample-worker\"}",
                    "legendFormat": "current",
                    "refId": "A"
                  },
                  {
                    "expr": "kube_deployment_spec_replicas{namespace=\"sample-fastapi\",deployment=\"sample-worker\"}",
                    "legendFormat": "spec",
                    "refId": "B"
                  }
                ]
              },
              {
                "id": 3,
                "title": "KEDA HPA Current vs Desired",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "short", "min": 0, "decimals": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "kube_horizontalpodautoscaler_status_current_replicas{namespace=\"sample-fastapi\",horizontalpodautoscaler=\"keda-hpa-sample-worker\"}",
                    "legendFormat": "current",
                    "refId": "A"
                  },
                  {
                    "expr": "kube_horizontalpodautoscaler_status_desired_replicas{namespace=\"sample-fastapi\",horizontalpodautoscaler=\"keda-hpa-sample-worker\"}",
                    "legendFormat": "desired",
                    "refId": "B"
                  }
                ]
              },
              {
                "id": 4,
                "title": "Worker Queue Events",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "ops", "min": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "sum(rate(worker_processed_total{namespace=\"sample-fastapi\"}[1m]))",
                    "legendFormat": "processed/s",
                    "refId": "A"
                  },
                  {
                    "expr": "sum(increase(sample_queue_retry_total{namespace=\"sample-fastapi\"}[5m]))",
                    "legendFormat": "retries/5m",
                    "refId": "B"
                  },
                  {
                    "expr": "sum(increase(sample_queue_recovered_total{namespace=\"sample-fastapi\"}[5m]))",
                    "legendFormat": "recovered/5m",
                    "refId": "C"
                  },
                  {
                    "expr": "sum(increase(sample_queue_dead_letter_total{namespace=\"sample-fastapi\"}[5m]))",
                    "legendFormat": "dead-letter/5m",
                    "refId": "D"
                  }
                ]
              },
              {
                "id": 5,
                "title": "Sample Pod CPU Usage",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 0, "y": 16 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "cores", "min": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "sum(rate(container_cpu_usage_seconds_total{namespace=\"sample-fastapi\",pod=~\"sample-(fastapi|worker)-.*\",container!=\"\",container!=\"POD\"}[5m])) by (pod)",
                    "legendFormat": "{{pod}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 6,
                "title": "Sample Pod Memory Working Set",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 12, "x": 12, "y": 16 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "bytes", "min": 0 },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "sum(container_memory_working_set_bytes{namespace=\"sample-fastapi\",pod=~\"sample-(fastapi|worker)-.*\",container!=\"\",container!=\"POD\"}) by (pod)",
                    "legendFormat": "{{pod}}",
                    "refId": "A"
                  }
                ]
              }
            ],
            "templating": {
              "list": [
                {
                  "name": "datasource",
                  "type": "datasource",
                  "query": "prometheus",
                  "current": {}
                }
              ]
            }
          }
      # 월간 리소스 사용 효율 보고서 (CPU, Memory, 스토리지, 영구볼륨, 네트워크)
      finops-sizing-optimization:
        json: |
          {
            "title": "월간 리소스 사용 효율 보고서 (Cost & Sizing Optimization)",
            "uid": "finops-sizing-optimization",
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "refresh": "1m",
            "time": { "from": "now-30d", "to": "now" },
            "tags": ["finops", "thanos", "optimization", "monthly"],
            "panels": [
              {
                "id": 1,
                "title": "🔥 [30일 종합] CPU 낭비량 TOP 5 (Cores)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 0, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "cores" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "pod", "container", "Value"]
                      }
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "topk(5, sum by (namespace, pod, container) (last_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[$__range])) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!=\"\", container!=\"POD\"}[$__range])))",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 2,
                "title": "💾 [30일 종합] Memory 낭비량 TOP 5 (Bytes)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 8, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "bytes" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "pod", "container", "Value"]
                      }
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "topk(5, sum by (namespace, pod, container) (last_over_time(kube_pod_container_resource_requests{resource=\"memory\", container!=\"\", container!=\"POD\"}[$__range])) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (avg_over_time(container_memory_working_set_bytes{container!=\"\", container!=\"POD\"}[$__range])))",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 3,
                "title": "🗄️ [30일 종합] 스토리지 사용/낭비량 TOP 5 (Bytes)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 16, "y": 0 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "bytes" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "pod", "Value"]
                      }
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "topk(5, (sum by (namespace, pod) (last_over_time(kube_pod_container_resource_requests{resource=\"ephemeral-storage\"}[$__range])) - on(namespace, pod) group_left() sum by (namespace, pod) (avg_over_time(kubelet_volume_stats_used_bytes[$__range]))) or on(namespace, pod) sum by (namespace, pod) (avg_over_time(kubelet_volume_stats_used_bytes[$__range])))",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 4,
                "title": "🚨 [30일 종합] CPU 사용 효율 20% 미만 파드 목록 (%)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 0, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "percent" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "pod", "container", "Value"]
                      }
                    }
                  },
                  {
                    "id": "sortBy",
                    "options": {
                      "fields": {},
                      "sort": [
                        {
                          "field": "Value",
                          "desc": true
                        }
                      ]
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "sort_desc(((sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!=\"\", container!=\"POD\"}[$__range]))) / (sum by (namespace, pod, container) (last_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[$__range]))) * 100) < 20)",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 5,
                "title": "💾 [30일 종합] 영구볼륨(PVC) 용량 효율 30% 미만 목록 (%)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 8, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "percent" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "persistentvolumeclaim", "Value"]
                      }
                    }
                  },
                  {
                    "id": "sortBy",
                    "options": {
                      "fields": {},
                      "sort": [
                        {
                          "field": "Value",
                          "desc": true
                        }
                      ]
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "sort_desc(((sum by (namespace, persistentvolumeclaim) (last_over_time(kubelet_volume_stats_used_bytes[$__range])) / sum by (namespace, persistentvolumeclaim) (last_over_time(kubelet_volume_stats_capacity_bytes[$__range]))) * 100) < 30)",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 6,
                "title": "🌐 [30일 종합] 파드 네트워크 수신량 TOP 5 (Bps)",
                "type": "table",
                "gridPos": { "h": 8, "w": 8, "x": 16, "y": 8 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": { "unit": "Bps" },
                  "overrides": []
                },
                "transformations": [
                  {
                    "id": "filterFieldsByName",
                    "options": {
                      "include": {
                        "names": ["namespace", "pod", "container", "Value"]
                      }
                    }
                  }
                ],
                "targets": [
                  {
                    "expr": "topk(5, sum by (namespace, pod, container) (rate(container_network_receive_bytes_total[$__range])))",
                    "format": "table",
                    "instant": true,
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 7,
                "title": "📈 [30일 시계열 추세] 네임스페이스별 CPU 낭비량 TOP 5 (Cores)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 0, "y": 16 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "cores",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "(sum by (namespace) (last_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[1h]) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!=\"\", container!=\"POD\"}[30m]))) > 0) and on(namespace) topk(5, sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[$__range]) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (rate(container_cpu_usage_seconds_total{container!=\"\", container!=\"POD\"}[$__range]))))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 8,
                "title": "📈 [30일 시계열 추세] 네임스페이스별 Memory 낭비량 TOP 5 (Bytes)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 8, "y": 16 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "bytes",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "(sum by (namespace) (last_over_time(kube_pod_container_resource_requests{resource=\"memory\", container!=\"\", container!=\"POD\"}[1h]) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (avg_over_time(container_memory_working_set_bytes{container!=\"\", container!=\"POD\"}[1h]))) > 0) and on(namespace) topk(5, sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource=\"memory\", container!=\"\", container!=\"POD\"}[$__range]) - on(namespace, pod, container) group_left() sum by (namespace, pod, container) (avg_over_time(container_memory_working_set_bytes{container!=\"\", container!=\"POD\"}[$__range]))))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 9,
                "title": "📈 [30일 시계열 추세] 네임스페이스별 스토리지 사용량 TOP 5 (Bytes)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 16, "y": 16 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "bytes",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "sum by (namespace) (avg_over_time(kubelet_volume_stats_used_bytes[1h])) and on(namespace) topk(5, sum by (namespace) (avg_over_time(kubelet_volume_stats_used_bytes[$__range])))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 10,
                "title": "📈 [30일 시계열 추세] 네임스페이스별 평균 CPU 사용 효율 TOP 5 (%)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 0, "y": 24 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "percent",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "clamp_max((sum by (namespace) (rate(container_cpu_usage_seconds_total{container!=\"\", container!=\"POD\"}[30m])) / sum by (namespace) (last_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[1h]))) * 100, 100) and on(namespace) topk(5, sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource=\"cpu\", container!=\"\", container!=\"POD\"}[$__range])))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 11,
                "title": "📈 [30일 시계열 추세] 주요 PVC별 용량 사용률 TOP 5 (%)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 8, "y": 24 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "percent",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "((sum by (namespace, persistentvolumeclaim) (last_over_time(kubelet_volume_stats_used_bytes[1h])) / sum by (namespace, persistentvolumeclaim) (last_over_time(kubelet_volume_stats_capacity_bytes[1h]))) * 100) and on(namespace, persistentvolumeclaim) topk(5, sum by (namespace, persistentvolumeclaim) (avg_over_time(kubelet_volume_stats_capacity_bytes[$__range])))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}} / {{persistentvolumeclaim}}",
                    "refId": "A"
                  }
                ]
              },
              {
                "id": 12,
                "title": "📈 [30일 시계열 추세] 네임스페이스별 네트워크 수신량 TOP 5 (Bps)",
                "type": "timeseries",
                "gridPos": { "h": 8, "w": 8, "x": 16, "y": 24 },
                "datasource": { "type": "prometheus", "uid": "$datasource" },
                "fieldConfig": {
                  "defaults": {
                    "unit": "Bps",
                    "custom": {
                      "drawStyle": "line",
                      "lineInterpolation": "smooth",
                      "connectNulls": true
                    }
                  },
                  "overrides": []
                },
                "targets": [
                  {
                    "expr": "sum by (namespace) (rate(container_network_receive_bytes_total[30m])) and on(namespace) topk(5, sum by (namespace) (rate(container_network_receive_bytes_total[$__range])))",
                    "interval": "1h",
                    "legendFormat": "{{namespace}}",
                    "refId": "A"
                  }
                ]
              }
            ],
            "templating": {
              "list": [
                {
                  "name": "datasource",
                  "type": "datasource",
                  "query": "prometheus",
                  "current": {
                    "text": "Thanos",
                    "value": "Thanos"
                  }
                }
              ]
            }
          }