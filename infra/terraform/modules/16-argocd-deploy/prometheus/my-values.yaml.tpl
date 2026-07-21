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
        - receiver: 'telegram'
          matchers:
            - namespace = "default"
    receivers:
      - name: 'null'
      - name: 'telegram'
        telegram_configs:
          - bot_token: '${telegram_bot_token}'
            chat_id: ${telegram_chat_id}
            parse_mode: 'HTML'
prometheus:
  prometheusSpec:
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
