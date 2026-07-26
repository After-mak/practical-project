import os
import re
import json
import time
import asyncio
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 환경변수로부터 모킹 모드 여부 확인. 기본값은 false(실제 모드) — 환경변수를 깜빡 빠뜨렸을 때
# 조용히 가짜 데이터로 동작하는 대신, krr 실행/Prometheus 연결이 실패하며 바로 드러나게 함
MOCK_INTEGRATION = os.getenv("MOCK_INTEGRATION", "false").lower() == "true"

# KRR 결과 TTL 캐시 (Key: namespace, Value: (전체 스캔 결과 dict, cached_at))
# KRR CLI는 -n <namespace> 옵션으로 실행 시 네임스페이스 내 모든 워크로드를 한 번에 스캔하므로
# deployment 단위가 아닌 namespace 단위로 캐시해서 반복 호출 시 KRR 재실행을 피합니다.
_krr_cache: Dict[str, tuple] = {}
KRR_CACHE_TTL_SECONDS = 300  # 5분 캐시 유지

# Mock 모드에서 시나리오 테스트용으로 제공하는 고정 워크로드 목록
_MOCK_WORKLOADS: Dict[str, dict] = {
    "oom-failed-api": {
        "current": {"cpu": "1000m", "memory": "2Gi"},
        "krr_recommended": {"cpu": "250m", "memory": "512Mi"}
    },
    "traffic-spike-api": {
        "current": {"cpu": "1000m", "memory": "2Gi"},
        "krr_recommended": {"cpu": "250m", "memory": "700Mi"}
    },
    "unstable-api": {
        "current": {"cpu": "1000m", "memory": "1.5Gi"},
        "krr_recommended": {"cpu": "300m", "memory": "500Mi"}
    },
    "stable-optimized-api": {
        "current": {"cpu": "1000m", "memory": "2Gi"},
        "krr_recommended": {"cpu": "200m", "memory": "512Mi"}
    },
}
_MOCK_DEFAULT = {
    "current": {"cpu": "1000m", "memory": "2Gi"},
    "krr_recommended": {"cpu": "300m", "memory": "800Mi"}
}

class KrrClient:
    """
    Robusta KRR(Kubernetes Resource Recommender) CLI를 asyncio subprocess로 비동기 실행하여
    프로메테우스 메트릭 기반 실시간 리소스 추천값을 조회하는 클라이언트입니다.

    - 비동기 실행: asyncio.create_subprocess_exec() 사용으로 이벤트 루프 블로킹 없음
    - TTL 캐시: 5분간 동일 네임스페이스 스캔 결과(네임스페이스 내 전체 워크로드)를 재사용하여
      불필요한 KRR 재실행 방지. 단일 deployment 조회도 내부적으로는 네임스페이스 전체를 스캔한 뒤
      필요한 항목만 추출하므로, 같은 네임스페이스라면 캐시가 공유됩니다.
    """
    def __init__(self, prometheus_url: str = ""):
        self.prometheus_url = prometheus_url.rstrip("/")

    async def get_recommendation(self, deployment_name: str, namespace: str) -> Optional[dict]:
        """
        지정된 namespace를 스캔하여 특정 deployment의 현재/추천 리소스 설정을 가져옵니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[KrrClient] Mock Mode - Generating mock data for {deployment_name} in {namespace}")
            return _MOCK_WORKLOADS.get(deployment_name, _MOCK_DEFAULT)

        namespace_scan = await self._scan_namespace(namespace)
        if namespace_scan is None:
            return None
        result = namespace_scan.get(deployment_name)
        if result is None:
            logger.warning(f"[KrrClient] KRR 결과에서 '{deployment_name}' (ns: {namespace})을 찾지 못했습니다.")
        return result

    async def get_namespace_recommendations(self, namespace: str) -> Dict[str, dict]:
        """
        지정된 namespace 내 모든 워크로드의 현재/추천 리소스 설정을 한 번에 가져옵니다.
        (CronJob의 네임스페이스 전수 분석 및 /analyze/namespace 엔드포인트에서 사용)
        """
        if MOCK_INTEGRATION:
            logger.info(f"[KrrClient] Mock Mode - Generating namespace-wide mock data for {namespace}")
            return dict(_MOCK_WORKLOADS)

        namespace_scan = await self._scan_namespace(namespace)
        return namespace_scan or {}

    async def _scan_namespace(self, namespace: str) -> Optional[Dict[str, dict]]:
        """KRR CLI를 비동기로 1회 실행해 namespace 내 모든 워크로드의 추천값을 조회하고 캐시합니다."""
        now = time.monotonic()
        if namespace in _krr_cache:
            cached_result, cached_at = _krr_cache[namespace]
            if now - cached_at < KRR_CACHE_TTL_SECONDS:
                logger.info(f"[KrrClient] Cache hit ({int(now - cached_at)}s ago): namespace={namespace}")
                return cached_result

        logger.info(f"[KrrClient] KRR CLI 비동기 실행 중 (namespace: {namespace})")
        try:
            proc = await asyncio.create_subprocess_exec(
                "krr", "simple",
                "--prometheus-url", self.prometheus_url,
                "-n", namespace,
                "--formatter", "json",  # KRR v1.x부터 --format이 아닌 --formatter (구 옵션명은 CLI 에러로 실패함)
                "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()  # 프로세스 정리
                logger.error("[KrrClient] KRR CLI 실행 타임아웃 (120초 초과)")
                return None

            if proc.returncode != 0:
                logger.error(f"[KrrClient] KRR CLI 실행 실패 (exit code {proc.returncode}): {stderr.decode()[:500]}")
                return None

            data = json.loads(stdout.decode())
            result = self._parse_krr_output(data, namespace)

            # 성공 시 캐시 저장 (빈 결과라도 재스캔 방지를 위해 캐시)
            _krr_cache[namespace] = (result, now)
            logger.info(f"[KrrClient] 결과 캐시 저장: namespace={namespace} ({len(result)}개 워크로드, TTL: {KRR_CACHE_TTL_SECONDS}s)")

            return result

        except FileNotFoundError:
            logger.error("[KrrClient] 'krr' 명령어를 찾을 수 없습니다. robusta-krr 패키지 설치 확인 필요.")
        except json.JSONDecodeError as e:
            logger.error(f"[KrrClient] KRR JSON 파싱 실패: {e}")
        except Exception as e:
            logger.error(f"[KrrClient] KRR 실행 중 예외: {e}")

        return None

    def _parse_krr_output(self, data, namespace: str) -> Dict[str, dict]:
        """KRR JSON 출력 전체를 파싱하여 {deployment_name: {current, krr_recommended}} 형태로 반환합니다.

        krr_recommended.cpu/memory는 KRR이 실제로 권장값을 산출하지 못했을 경우(사용 이력 데이터 부족으로
        '?'를 반환한 경우) None이 됩니다. 이를 임의의 숫자(예: 500m)로 대체하면 마치 KRR이 그 값을 추천한
        것처럼 보여 운영자를 오도하므로, 상위 계층(main.py/engine.py)이 '데이터 부족'임을 그대로 알 수 있도록
        None을 그대로 전달합니다. 반면 current(현재 설정값)는 리소스에 request가 아예 설정되어 있지 않은
        경우가 흔하므로, 그 경우엔 실제 상태 그대로 0으로 표기합니다."""
        scans = data if isinstance(data, list) else data.get("scans", [])
        results: Dict[str, dict] = {}

        for scan in scans:
            obj = scan.get("object", {}) or {}
            if obj.get("namespace") != namespace:
                continue
            name = obj.get("name")
            if not name:
                continue

            recommended = scan.get("recommended", {}) or {}
            current_alloc = obj.get("allocations", {}) or {}

            rec_requests = recommended.get("requests", {}) or {}
            curr_requests = current_alloc.get("requests", {}) or {}

            results[name] = {
                "current": {
                    "cpu": self._format_resource_value(curr_requests.get("cpu"), "cpu") or "0m",
                    "memory": self._format_resource_value(curr_requests.get("memory"), "memory") or "0Mi"
                },
                "krr_recommended": {
                    "cpu": self._format_resource_value(rec_requests.get("cpu"), "cpu"),
                    "memory": self._format_resource_value(rec_requests.get("memory"), "memory")
                }
            }

        return results

    @staticmethod
    def _format_resource_value(val, resource: str) -> Optional[str]:
        """KRR 값(코어/바이트 단위 float, {'value': ...} dict, 또는 데이터 부족 시의 '?' 문자열)을
        K8s 형식 문자열로 변환합니다. 값이 없거나('None') 미확정('?')이면 '알 수 없음'을 그대로
        나타내기 위해 None을 반환합니다 — 임의의 숫자로 추측해서 채우지 않습니다."""
        if isinstance(val, dict):
            val = val.get("value")
        if val is None or isinstance(val, str):
            return None
        val = float(val)
        if resource == "cpu":
            if val < 1.0:
                return f"{int(round(val * 1000))}m"
            return str(round(val, 2))
        else:
            mib = val / (1024.0 * 1024.0)
            if mib >= 1024.0 and mib % 1024.0 == 0:
                return f"{int(mib / 1024.0)}Gi"
            return f"{int(round(mib))}Mi"


class PrometheusClient:
    def __init__(self, prometheus_url: str = ""):
        self.prometheus_url = prometheus_url.rstrip("/")

    @staticmethod
    def _pod_regex(deployment_name: str) -> str:
        """deployment_name을 PromQL 레이블 정규식에 안전하게 삽입하기 위한 이스케이프 처리.
        'payment.api'처럼 정규식 특수문자가 포함된 이름이 들어와도 '.'이 '임의의 문자'로
        해석되어 엉뚱한 파드까지 매치되거나 PromQL 파싱이 깨지는 것을 방지합니다."""
        return "^" + re.escape(deployment_name) + "-[a-z0-9]+-[a-z0-9]+$"

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
            pod_regex = self._pod_regex(deployment_name)
            # Pod의 CPU Request 수치 쿼리 (코어 단위)
            cpu_req_query = f'avg(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{pod_regex}"}})'
            cpu_val = self._query_prometheus(cpu_req_query)

            # Pod의 Memory Request 수치 쿼리 (Byte 단위)
            mem_req_query = f'avg(kube_pod_container_resource_requests{{resource="memory", namespace="{namespace}", pod=~"{pod_regex}"}})'
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
            pod_regex = self._pod_regex(deployment_name)
            # 1. OOM Killed 이벤트 쿼리
            oom_query = f'sum(increase(kube_pod_container_status_terminated_reason{{namespace="{namespace}", pod=~"{pod_regex}", reason="OOMKilled"}}[24h]))'
            oom_res = self._query_prometheus(oom_query)
            if oom_res and oom_res > 0:
                metrics["oom_killed"] = True

            # 2. Pod 재시작 횟수 쿼리
            restart_query = f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}", pod=~"{pod_regex}"}})'
            restart_res = self._query_prometheus(restart_query)
            if restart_res is not None:
                metrics["restart_count"] = int(restart_res)

            # 3. 평균 CPU 사용률 (%) 쿼리
            cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"{pod_regex}", container!=""}}[5m])) / sum(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{pod_regex}"}}) * 100'
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
            "parse_mode": "HTML"
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
