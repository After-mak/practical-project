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

# KRR cache key includes namespace and explicit history duration.
_krr_cache: Dict[tuple[str, str], tuple] = {}
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
    def __init__(self, prometheus_url: str = "", history_duration: str = ""):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.history_duration = history_duration or os.getenv("KRR_HISTORY_DURATION", "336h")

    async def get_recommendation(
        self,
        deployment_name: str,
        namespace: str,
        container_name: Optional[str] = None,
        history_duration: Optional[str] = None,
    ) -> Optional[dict]:
        """Return one container recommendation; ambiguous workload-only lookups fail."""
        if MOCK_INTEGRATION:
            value = dict(_MOCK_WORKLOADS.get(deployment_name, _MOCK_DEFAULT))
            value.update({"namespace": namespace, "workload": deployment_name, "container": container_name or deployment_name})
            return value

        namespace_scan = await self._scan_namespace(namespace, history_duration)
        if namespace_scan is None:
            return None
        if container_name:
            return namespace_scan.get(f"{namespace}/{deployment_name}/{container_name}")
        candidates = [value for value in namespace_scan.values() if value["workload"] == deployment_name]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.error(
                "[KrrClient] '%s/%s' has %d containers; container_name is required.",
                namespace, deployment_name, len(candidates),
            )
        else:
            logger.warning("[KrrClient] KRR result missing for '%s/%s'.", namespace, deployment_name)
        return None

    async def get_namespace_recommendations(
        self, namespace: str, history_duration: Optional[str] = None
    ) -> Dict[str, dict]:
        """Return namespace/workload/container keyed recommendations."""
        if MOCK_INTEGRATION:
            return {
                f"{namespace}/{name}/{name}": {
                    **value, "namespace": namespace, "workload": name, "container": name,
                }
                for name, value in _MOCK_WORKLOADS.items()
            }
        namespace_scan = await self._scan_namespace(namespace, history_duration)
        return namespace_scan or {}

    async def _scan_namespace(
        self, namespace: str, history_duration: Optional[str] = None
    ) -> Optional[Dict[str, dict]]:
        """Run KRR once for one namespace and an explicit history duration."""
        duration = history_duration or self.history_duration
        match = re.fullmatch(r"([1-9][0-9]*)(h|d|w)?", duration)
        if not match:
            raise ValueError(f"invalid KRR history_duration: {duration!r}; use hours (24 or 24h), days, or weeks")
        amount = int(match.group(1))
        unit = match.group(2) or "h"
        duration_hours = str(amount * {"h": 1, "d": 24, "w": 168}[unit])
        cache_key = (namespace, duration_hours)
        now = time.monotonic()
        if cache_key in _krr_cache:
            cached_result, cached_at = _krr_cache[cache_key]
            if now - cached_at < KRR_CACHE_TTL_SECONDS:
                logger.info(
                    "[KrrClient] Cache hit (%ss ago): namespace=%s history=%s",
                    int(now - cached_at), namespace, duration_hours,
                )
                return cached_result

        logger.info("[KrrClient] KRR scan: namespace=%s history=%s", namespace, duration_hours)
        try:
            proc = await asyncio.create_subprocess_exec(
                "krr", "simple",
                "--prometheus-url", self.prometheus_url,
                "-n", namespace,
                "--formatter", "json",
                "--cpu_percentile", "95",
                "--history_duration", duration_hours,
                "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.error("[KrrClient] KRR CLI timed out after 120 seconds")
                return None
            if proc.returncode != 0:
                logger.error(
                    "[KrrClient] KRR CLI failed (exit %s): %s",
                    proc.returncode, stderr.decode()[:500],
                )
                return None
            result = self._parse_krr_output(json.loads(stdout.decode()), namespace)
            _krr_cache[cache_key] = (result, now)
            logger.info("[KrrClient] cached %d container recommendations", len(result))
            return result
        except FileNotFoundError:
            logger.error("[KrrClient] krr executable was not found")
        except json.JSONDecodeError as exc:
            logger.error("[KrrClient] failed to parse KRR JSON: %s", exc)
        except Exception as exc:
            logger.error("[KrrClient] KRR execution failed: %s", exc)
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
            container = obj.get("container")
            if not name or not container:
                logger.warning("[KrrClient] skipping KRR row without workload/container: %s", obj)
                continue
            kind = obj.get("kind")
            if kind in ("Job", "GroupedJob"):
                # k6 부하테스트 Job(예: bank-loadgen-*)처럼 일회성으로 실행되고 끝나는 워크로드는
                # 리사이징 대상이 아니라 다른 서비스에 부하를 주는 도구입니다. 그대로 승인
                # 목록에 올리면 자동 생성된 긴 실행 이름이 텔레그램 콜백 데이터 길이 제한을
                # 넘겨 배치 승인 메시지 전체를 실패시키는 문제도 있어(재현 확인함) 아예 제외합니다.
                logger.info("[KrrClient] skipping non-rightsizing workload kind=%s: %s/%s", kind, namespace, name)
                continue
            identifier = f"{namespace}/{name}/{container}"
            recommended = scan.get("recommended", {}) or {}
            current_alloc = obj.get("allocations", {}) or {}

            rec_requests = recommended.get("requests", {}) or {}
            curr_requests = current_alloc.get("requests", {}) or {}
            curr_limits = current_alloc.get("limits", {}) or {}

            results[identifier] = {
                "namespace": namespace,
                "workload": name,
                "container": container,
                "kind": obj.get("kind"),
                "current": {
                    "cpu": self._format_resource_value(curr_requests.get("cpu"), "cpu") or "0m",
                    "memory": self._format_resource_value(curr_requests.get("memory"), "memory") or "0Mi"
                },
                "krr_recommended": {
                    "cpu": self._format_resource_value(rec_requests.get("cpu"), "cpu"),
                    "memory": self._format_resource_value(rec_requests.get("memory"), "memory")
                },
                # 현재 배포된 컨테이너의 limits. requests > limits는 Kubernetes가 반영 자체를 거부하므로
                # 정책 엔진이 최종 권장값을 이 값 이하로 캡 걸 때 사용합니다. limits가 설정 안 돼있으면 None.
                "current_limits": {
                    "cpu": self._format_resource_value(curr_limits.get("cpu"), "cpu"),
                    "memory": self._format_resource_value(curr_limits.get("memory"), "memory")
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
        if val is None:
            return None
        if isinstance(val, str):
            val = val.strip()
            if not val or val == "?":
                return None
            if resource == "cpu" and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[num]", val):
                return val
            if resource == "memory" and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:[KMGTPE]i?|m)", val):
                return val
            try:
                val = float(val)
            except ValueError:
                logger.warning("[KrrClient] unsupported %s resource value: %r", resource, val)
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

    def get_current_resource_spec(self, deployment_name: str, namespace: str, container_name: Optional[str] = None) -> Optional[dict]:
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
            container_filter = f', container="{container_name}"' if container_name else ''
            usage_filter = container_filter or ', container!="", container!="POD"'
            # Pod의 CPU Request 수치 쿼리 (코어 단위)
            cpu_req_query = f'avg(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{pod_regex}"{container_filter}}})'
            cpu_val = self._query_prometheus(cpu_req_query)

            # Pod의 Memory Request 수치 쿼리 (Byte 단위)
            mem_req_query = f'avg(kube_pod_container_resource_requests{{resource="memory", namespace="{namespace}", pod=~"{pod_regex}"{container_filter}}})'
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

    def get_workload_metrics(self, deployment_name: str, namespace: str, container_name: Optional[str] = None) -> Optional[dict]:
        """
        Prometheus로부터 최근 워크로드의 OOM Kill 발생 여부, Restart 횟수, 평균 CPU 로드를 조회합니다.
        """
        if MOCK_INTEGRATION:
            logger.info(f"[PrometheusClient] Mock Mode - Generating mock data for {deployment_name}")
            if deployment_name == "oom-failed-api":
                return {
                    "oom_killed": True,       # OOM 발생 시나리오
                    "restart_count": 2,
                    "avg_cpu_usage_pct": 72.5,
                    "throttled": True          # OOM과 함께 CPU도 압박받는 시나리오
                }
            elif deployment_name == "unstable-api":
                return {
                    "oom_killed": False,
                    "restart_count": 15,      # 재시작 10회 이상 시나리오
                    "avg_cpu_usage_pct": 40.0,
                    "throttled": False
                }
            elif deployment_name == "stable-optimized-api":
                return {
                    "oom_killed": False,
                    "restart_count": 0,
                    "avg_cpu_usage_pct": 12.0, # 저부하 경부하 시나리오
                    "throttled": False
                }
            else: # 일반 정상 최적화 케이스 (payment-api 등)
                return {
                    "oom_killed": False,
                    "restart_count": 0,
                    "avg_cpu_usage_pct": 35.0,
                    "throttled": False
                }

        # 실제 Prometheus REST API (/api/v1/query) PromQL 수행
        logger.info(f"[PrometheusClient] Real PromQL Querying -> {self.prometheus_url}")
        metrics = {
            "oom_killed": False,
            "restart_count": 0,
            "avg_cpu_usage_pct": None,
            "throttled": False
        }

        try:
            pod_regex = self._pod_regex(deployment_name)
            container_filter = f', container="{container_name}"' if container_name else ''
            usage_filter = container_filter or ', container!="", container!="POD"'
            # 1. OOM Killed 이벤트 쿼리
            oom_query = f'sum(increase(kube_pod_container_status_terminated_reason{{namespace="{namespace}", pod=~"{pod_regex}"{container_filter}, reason="OOMKilled"}}[24h]))'
            oom_res = self._query_prometheus(oom_query)
            if oom_res and oom_res > 0:
                metrics["oom_killed"] = True

            # 2. Pod 재시작 횟수 쿼리
            restart_query = f'sum(kube_pod_container_status_restarts_total{{namespace="{namespace}", pod=~"{pod_regex}"{container_filter}}})'
            restart_res = self._query_prometheus(restart_query)
            if restart_res is not None:
                metrics["restart_count"] = int(restart_res)

            # 3. 평균 CPU 사용률 (%) 쿼리
            cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"{pod_regex}"{usage_filter}}}[5m])) / sum(kube_pod_container_resource_requests{{resource="cpu", namespace="{namespace}", pod=~"{pod_regex}"{container_filter}}}) * 100'
            cpu_res = self._query_prometheus(cpu_query)
            if cpu_res is not None:
                metrics["avg_cpu_usage_pct"] = round(float(cpu_res), 2)

            # 4. CPU Throttling 발생 여부 쿼리 (cAdvisor)
            throttle_query = f'sum(increase(container_cpu_cfs_throttled_periods_total{{namespace="{namespace}", pod=~"{pod_regex}", container!=""}}[24h]))'
            throttle_res = self._query_prometheus(throttle_query)
            if throttle_res and throttle_res > 0:
                metrics["throttled"] = True

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
        namespace: str = "",
        container_name: str = ""
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
            context_suffix = f":{namespace}:{deployment_name}:{container_name}" if namespace and deployment_name and container_name else ""
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


class TgGatewayClient:
    """
    finops가 텔레그램 API(TelegramClient)를 직접 호출하지 않고, tg-gateway(alarm 서비스)를
    거쳐 발송합니다. 실제 sendDocument/sendMessage 호출과 인라인 버튼 콜백 처리는
    tg-gateway가 전담하고, finops는 "무엇을 보여줄지"(리포트 내용)만 결정합니다.
    """
    def __init__(self, gateway_url: str = ""):
        self.gateway_url = gateway_url.rstrip("/")

    def send_batch_report_file(self, filename: str, content: str, caption: str) -> bool:
        """전체 워크로드 상세 리포트를 파일 하나로 묶어 tg-gateway에 전달합니다.
        승인/거절 메시지보다 먼저 보내서 필요하면 따로 열어볼 수 있게 합니다."""
        if not self.gateway_url:
            logger.debug("[TgGatewayClient] gateway_url이 설정되지 않아 발송을 스킵합니다.")
            return False
        try:
            resp = requests.post(
                f"{self.gateway_url}/webhook/deploy-batch-report",
                files={"file": (filename, content.encode("utf-8"), "text/plain")},
                data={"caption": caption},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            logger.warning(f"[TgGatewayClient] 리포트 파일 전송 실패: {resp.status_code} {resp.text[:300]}")
        except Exception as e:
            logger.error(f"[TgGatewayClient] 리포트 파일 전송 에러: {e}")
        return False

    def send_batch_approval(self, workloads: list) -> bool:
        """워크로드 전체를 담은 승인/거절 메시지 하나를 tg-gateway에 전달합니다.
        workloads의 각 항목은 {namespace, deployment_name, container_name, overall_status, line}
        형태이며, tg-gateway는 line들을 이어붙여 본문을 만들고 overall_status=="PASS"인
        항목에만 승인/거절 버튼 한 줄씩을 붙입니다."""
        if not self.gateway_url:
            logger.debug("[TgGatewayClient] gateway_url이 설정되지 않아 발송을 스킵합니다.")
            return False
        try:
            resp = requests.post(
                f"{self.gateway_url}/webhook/deploy-batch-approval",
                json={"workloads": workloads},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            logger.warning(f"[TgGatewayClient] 승인 메시지 전송 실패: {resp.status_code} {resp.text[:300]}")
        except Exception as e:
            logger.error(f"[TgGatewayClient] 승인 메시지 전송 에러: {e}")
        return False


class KrrDbClient:
    """
    KRR 분석 결과를 CNPG 데이터베이스(krr_logs_db)의 krr_logs 테이블에 저장하는 부분.
    """
    def __init__(self, db_uri: str = ""):
        self.db_uri = db_uri or os.getenv("KRR_DB_URI", "") or os.getenv("DATABASE_URL", "")
        if not self.db_uri and os.getenv("DB_HOST"):
            user = os.getenv("DB_USER", "scott")
            password = os.getenv("DB_PASSWORD", "tiger")
            host = os.getenv("DB_HOST", "krr-data-db-rw.default.svc.cluster.local")
            port = os.getenv("DB_PORT", "5432")
            dbname = os.getenv("DB_NAME", "krr_logs_db")
            self.db_uri = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        # Grafana 시각화용 컬럼(cost_savings_pct 등)을 기존 krr_logs 테이블에 매번 새로
        # ALTER 실행하지 않도록, 프로세스 생명주기 동안 한 번만 보강하면 되는지 추적하는 플래그.
        self._schema_ensured = False

    def _ensure_schema(self, cur) -> None:
        """krr_logs 테이블에 Grafana 시각화용 컬럼이 없으면 추가합니다 (idempotent).
        별도 마이그레이션 도구가 없는 프로젝트라, 이미 만들어져 있는 테이블 위에
        안전하게 컬럼만 보강하는 방식을 씁니다."""
        if self._schema_ensured:
            return
        cur.execute("""
            ALTER TABLE krr_logs
                ADD COLUMN IF NOT EXISTS container_name VARCHAR(255) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS cost_savings_pct DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS cost_savings_amount DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS current_cost DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS final_cost DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS cpu_utilization_pct DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS oom_killed BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS throttled BOOLEAN DEFAULT FALSE
        """)
        self._schema_ensured = True

    def save_log(
        self,
        namespace: str,
        deployment_name: str,
        container_name: str,
        cpu_current: str,
        cpu_recommended: str,
        mem_current: str,
        mem_recommended: str,
        cost_savings_pct: float = 0.0,
        cost_savings_amount: float = 0.0,
        current_cost: float = 0.0,
        final_cost: float = 0.0,
        cpu_utilization_pct: Optional[float] = None,
        oom_killed: bool = False,
        throttled: bool = False
    ) -> bool:
        if not self.db_uri:
            logger.debug("[KrrDbClient] KRR_DB_URI 또는 DB_HOST가 설정되지 않아 DB 저장을 스킵합니다.")
            return False

        try:
            import psycopg2
            with psycopg2.connect(self.db_uri, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    self._ensure_schema(cur)
                    query = """
                        INSERT INTO krr_logs (
                            namespace, deployment_name, container_name,
                            cpu_current, cpu_recommended,
                            mem_current, mem_recommended,
                            cost_savings_pct, cost_savings_amount,
                            current_cost, final_cost,
                            cpu_utilization_pct, oom_killed, throttled
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cur.execute(query, (
                        namespace,
                        deployment_name,
                        container_name,
                        str(cpu_current),
                        str(cpu_recommended),
                        str(mem_current),
                        str(mem_recommended),
                        cost_savings_pct,
                        cost_savings_amount,
                        current_cost,
                        final_cost,
                        cpu_utilization_pct,
                        oom_killed,
                        throttled
                    ))
                conn.commit()
            logger.info(f"[KrrDbClient] Successfully inserted log for '{namespace}/{deployment_name}/{container_name}' into krr_logs table!")
            return True
        except ImportError:
            logger.error("[KrrDbClient] psycopg2-binary 라이브러리가 설치되지 않았습니다.")
            return False
        except Exception as e:
            logger.error(f"[KrrDbClient] Error inserting log into DB: {e}")
            return False
