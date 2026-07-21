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
    serviceMonitorSelector:
      matchLabels:
        monitoring: prometheus
    serviceMonitorNamespaceSelector:
      matchLabels:
        monitoring: prometheus
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 500m
        memory: 1Gi
    retention: 7d
grafana:
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 100m
      memory: 256Mi
  adminPassword: "${grafana_admin_password}"
