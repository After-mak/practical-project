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
    # KRR 더미 이력 데이터를 Prometheus가 뜨기 전에 미리 채워 넣는 initContainer입니다.
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
          - name: SCENARIOS_NS
            value: "sample-fastapi"
        volumeMounts:
          - name: prometheus-prometheus-stack-kube-prom-prometheus-db
            mountPath: /prometheus
%{ endif ~}
grafana:
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
