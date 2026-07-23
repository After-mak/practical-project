import os
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 환경변수로부터 모킹 모드 여부 확인
MOCK_INTEGRATION = os.getenv("MOCK_INTEGRATION", "true").lower() == "true"

class KrrClient:
    def __init__(self, krr_url: str = ""):
        self.krr_url = krr_url.rstrip("/")

    def get_recommendation(self, deployment_name: str, namespace: str) -> dict:
        """
        KRR 추천 엔진으로부터 현재 리소스 설정과 추천 리소스 설정을 가져옵니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[KrrClient] Mock Mode - Generating mock data for {deployment_name} in {namespace}")
            # 테스트 시나리오별 모킹 데이터 분기 (sample-fastapi 브랜치 시나리오 호환)
            if deployment_name == "oom-failed-api":
                return {
                    "current": {"cpu": "1000m", "memory": "2Gi"},
                    "krr_recommended": {"cpu": "250m", "memory": "512Mi"} # 메모리 과도 감축 제안 시나리오
                }
            elif deployment_name == "traffic-spike-api":
                return {
                    "current": {"cpu": "1000m", "memory": "2Gi"},
                    "krr_recommended": {"cpu": "250m", "memory": "700Mi"}
                }
            elif deployment_name == "unstable-api":
                return {
                    "current": {"cpu": "1000m", "memory": "1.5Gi"},
                    "krr_recommended": {"cpu": "300m", "memory": "500Mi"}
                }
            elif deployment_name == "stable-optimized-api":
                return {
                    "current": {"cpu": "1000m", "memory": "2Gi"},
                    "krr_recommended": {"cpu": "200m", "memory": "512Mi"}
                }
            else: # 일반 정상 최적화 케이스 (payment-api 등)
                return {
                    "current": {"cpu": "1000m", "memory": "2Gi"},
                    "krr_recommended": {"cpu": "300m", "memory": "800Mi"}
                }
        
        # 실제 KRR REST API / Exporter 호출 진행
        logger.info(f"[KrrClient] Real API Call -> {self.krr_url}/api/v1/recommendations/{namespace}/{deployment_name}")
        try:
            url = f"{self.krr_url}/api/v1/recommendations/{namespace}/{deployment_name}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "current": data.get("current", {"cpu": "1000m", "memory": "2Gi"}),
                    "krr_recommended": data.get("krr_recommended", {"cpu": "500m", "memory": "1Gi"})
                }
            else:
                logger.warning(f"[KrrClient] KRR API status {resp.status_code}, returning None")
        except Exception as e:
            logger.error(f"[KrrClient] Error calling KRR API: {e}")

        return None

class PrometheusClient:
    def __init__(self, prometheus_url: str = ""):
        self.prometheus_url = prometheus_url.rstrip("/")

    def get_current_resource_spec(self, deployment_name: str, namespace: str) -> Optional[dict]:
        """
        Prometheus 메트릭(kube_pod_container_resource_requests 또는 cAdvisor)으로부터 
        현재 워크로드의 실제 설정/사용량 CPU 및 Memory 데이터를 직접 수집합니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[PrometheusClient] Mock Mode - Returning mock current spec for {deployment_name}")
            return {"cpu": "1000m", "memory": "2Gi"}

        try:
            logger.info(f"[PrometheusClient] Querying current CPU/Mem resource specs from Prometheus")
            # Pod의 CPU Request 수치 쿼리 (코어 단위)
            cpu_req_query = f'avg(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+"}})'
            cpu_val = self._query_prometheus(cpu_req_query)

            # Pod의 Memory Request 수치 쿼리 (Byte 단위)
            mem_req_query = f'avg(kube_pod_container_resource_requests{{resource="memory", namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+"}})'
            mem_val = self._query_prometheus(mem_req_query)

            if cpu_val is not None and mem_val is not None:
                # CPU: m 단위 변환 (예: 1.0 -> 1000m, 0.5 -> 500m)
                cpu_str = f"{int(round(cpu_val * 1000))}m" if cpu_val < 1.0 else f"{round(cpu_val, 2)}"
                # Memory: Gi/Mi 단위 변환
                mem_mib = mem_val / (1024.0 * 1024.0)
                mem_str = f"{round(mem_mib / 1024.0, 2)}Gi" if mem_mib >= 1024.0 else f"{int(round(mem_mib))}Mi"

                return {
                    "cpu": cpu_str,
                    "memory": mem_str
                }
        except Exception as e:
            logger.error(f"[PrometheusClient] Error querying current spec from Prometheus: {e}")

        return None

    def get_workload_metrics(self, deployment_name: str, namespace: str) -> Optional[dict]:
        """
        Prometheus로부터 최근 워크로드의 OOM Kill 발생 여부, Restart 횟수, 평균 CPU 로드를 조회합니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[PrometheusClient] Mock Mode - Generating mock data for {deployment_name}")
            if deployment_name == "oom-failed-api":
                return {
                    "oom_killed": True,       # OOM 발생 시나리오
                    "restart_count": 2,
                    "avg_cpu_usage_pct": 72.5
                }
            elif deployment_name == "unstable-api":
                return {
                    "oom_killed": False,
                    "restart_count": 15,      # 재시작 10회 이상 시나리오
                    "avg_cpu_usage_pct": 40.0
                }
            elif deployment_name == "stable-optimized-api":
                return {
                    "oom_killed": False,
                    "restart_count": 0,
                    "avg_cpu_usage_pct": 12.0 # 저부하 경부하 시나리오
                }
            else: # 일반 정상 최적화 케이스 (payment-api 등)
                return {
                    "oom_killed": False,
                    "restart_count": 0,
                    "avg_cpu_usage_pct": 35.0
                }

        # 실제 Prometheus REST API (/api/v1/query) PromQL 수행
        logger.info(f"[PrometheusClient] Real PromQL Querying -> {self.prometheus_url}")
        metrics = {
            "oom_killed": False,
            "restart_count": 0,
            "avg_cpu_usage_pct": None
        }

        try:
            # 1. OOM Killed 이벤트 쿼리
            oom_query = f'sum(increase(kube_pod_container_status_terminated_reason{{namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+", reason="OOMKilled"}}[24h]))'
            oom_res = self._query_prometheus(oom_query)
            if oom_res and oom_res > 0:
                metrics["oom_killed"] = True

            # 2. Pod 재시작 횟수 쿼리
            restart_query = f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+"}})'
            restart_res = self._query_prometheus(restart_query)
            if restart_res is not None:
                metrics["restart_count"] = int(restart_res)

            # 3. 평균 CPU 사용률 (%) 쿼리
            cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+", container!=""}}[5m])) / sum(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{deployment_name}-[a-z0-9]+-[a-z0-9]+"}}) * 100'
            cpu_res = self._query_prometheus(cpu_query)
            if cpu_res is not None:
                metrics["avg_cpu_usage_pct"] = round(float(cpu_res), 2)

            return metrics

        except Exception as e:
            logger.error(f"[PrometheusClient] Error querying Prometheus: {e}")

        return None

    def _query_prometheus(self, query: str) -> Optional[float]:
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            resp = requests.get(url, params={"query": query}, timeout=5)
            if resp.status_code == 200:
                result = resp.json().get("data", {}).get("result", [])
                if result and len(result) > 0:
                    val = result[0].get("value", [None, "0"])[1]
                    return float(val)
        except Exception as e:
            logger.debug(f"[PrometheusClient] Query '{query}' failed: {e}")
        return None

class ChronosClient:
    def __init__(self, chronos_url: str = ""):
        self.chronos_url = chronos_url.rstrip("/")

    def get_future_forecast(self, deployment_name: str, namespace: str) -> Optional[dict]:
        """
        Chronos-2 시계열 예측 모델로부터 향후 10분간의 예상 최대 CPU 부하, 메모리 부하, 트래픽을 조회합니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[ChronosClient] Mock Mode - Generating mock data for {deployment_name}")
            if deployment_name == "traffic-spike-api":
                return {
                    "predicted_max_cpu_pct": 92.0,  # CPU 92% 폭증 예측 시나리오
                    "predicted_max_mem_pct": 80.0,
                    "predicted_req_per_sec": 4500.0
                }
            else: # 일반 정상 최적화 케이스
                return {
                    "predicted_max_cpu_pct": 42.0,
                    "predicted_max_mem_pct": 50.0,
                    "predicted_req_per_sec": 1200.0
                }

        logger.info(f"[ChronosClient] Real API Call -> {self.chronos_url}/predict/{namespace}/{deployment_name}")
        try:
            url = f"{self.chronos_url}/predict/{namespace}/{deployment_name}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_max_cpu_pct": float(data["predicted_max_cpu_pct"]) if data.get("predicted_max_cpu_pct") is not None else None,
                    "predicted_max_mem_pct": float(data["predicted_max_mem_pct"]) if data.get("predicted_max_mem_pct") is not None else None,
                    "predicted_req_per_sec": float(data["predicted_req_per_sec"]) if data.get("predicted_req_per_sec") is not None else None
                }
        except Exception as e:
            logger.error(f"[ChronosClient] Error calling Chronos API: {e}")

        return None

class TelegramClient:
    """
    텔레그램 봇 API를 이용해 FinOps 분석 리포트 및 인라인 승인/거부 버튼 메시지를 발송하는 클라이언트.
    alarm/send_report.sh 및 alarm/main.py 게이트웨이 규격과 100% 호환됩니다.
    """
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token.strip('"').strip("'")
        self.chat_id = chat_id.strip('"').strip("'")

    def send_report(
        self,
        message_text: str,
        overall_status: str,
        deployment_name: str = "",
        namespace: str = ""
    ) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("[TelegramClient] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않아 발송을 스킵합니다.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {
            "chat_id": self.chat_id,
            "text": message_text,
            "parse_mode": "Markdown"
        }

        # PASS 상태인 경우 운영자 승인/거부 인라인 키보드 버튼 첨부 (워크로드 컨텍스트 포함)
        if overall_status == "PASS":
            context_suffix = f":{namespace}:{deployment_name}" if namespace and deployment_name else ""
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {"text": "✅ 승인 (Apply)", "callback_data": f"infra_approve{context_suffix}"},
                    {"text": "❌ 거부 (Reject)", "callback_data": f"infra_reject{context_suffix}"}
                ]]
            }

        try:
            logger.info(f"[TelegramClient] Sending report to chat_id: {self.chat_id}")
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("[TelegramClient] Report sent successfully to Telegram!")
                return True
            else:
                logger.warning(f"[TelegramClient] Telegram API Warning: {resp.status_code} - {resp.text}. Trying fallback plain-text mode.")
                # Telegram Markdown entity parsing fallback
                payload.pop("parse_mode", None)
                fallback_resp = requests.post(url, json=payload, timeout=10)
                if fallback_resp.status_code == 200 and fallback_resp.json().get("ok"):
                    logger.info("[TelegramClient] Report sent via plain-text fallback successfully!")
                    return True
        except Exception as e:
            logger.error(f"[TelegramClient] Exception during Telegram dispatch: {e}")

        return False
