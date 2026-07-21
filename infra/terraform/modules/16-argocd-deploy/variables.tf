variable "telegram_bot_token" {
  description = "모니터링 Alertmanager가 사용할 텔레그램 봇 토큰"
  type        = string
  sensitive   = true
}

variable "telegram_chat_id" {
  description = "모니터링 알림을 받을 텔레그램 chat_id"
  type        = number
  sensitive   = true
}

variable "grafana_admin_password" {
  description = "Grafana admin 계정 비밀번호"
  type        = string
  sensitive   = true
}
