import os
import json
import time
import shutil
import logging
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, HTTPException, status
from app.schemas import (
    AnalysisRequest, AnalysisResponse, NamespaceAnalysisRequest, NamespaceAnalysisResponse,
    ResourceSpec, PrometheusMetrics, ChronosForecast
)
from app.clients import KrrClient, PrometheusClient, ChronosClient, TelegramClient, KrrDbClient
from app.engine import PolicyEngine, parse_cpu, parse_memory
from app.formatter import ReportFormatter

# ==========================================
# 로깅 설정 (LOG_FORMAT=json 이면 구조화 로그로 출력하여
# CloudWatch/Datadog 등에서 파싱/트레이싱이 가능하도록 함)
# ==========================================
class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

_log_handler = logging.StreamHandler()
if os.getenv("LOG_FORMAT", "text").lower() == "json":
    _log_handler.setFormatter(JsonLogFormatter())
else:
    _log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI 기반 FinOps 정책 분석 엔진 API",
    description="KRR 추천값 및 Prometheus/Chronos-2 메트릭을 분석하여 최적의 안전 리소스 권장안을 생성하고 텔레그램 승인 알림을 발송하는 정책 엔진 API",
    version="1.2.0"
)

# API 엔드포인트 URL 및 텔레그램 설정 (환경변수 참조)
# MOCK_INTEGRATION 기본값은 false(실제 모드) — clients.py와 동일한 이유
MOCK_INTEGRATION = os.getenv("MOCK_INTEGRATION", "false").lower() == "true"
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus-stack-kube-prom-prometheus.prometheus.svc.cluster.local:9090")
CHRONOS_URL = os.getenv("CHRONOS_URL", "http://chronos-model.monitoring.svc.cluster.local:8000")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
AUTO_SEND_TELEGRAM = os.getenv("AUTO_SEND_TELEGRAM", "false").lower() == "true"

# 클라이언트 인스턴스화 (KRR은 별도 서비스가 아닌 내부 CLI로 실행되므로 prometheus_url을 전달)
krr_client = KrrClient(PROMETHEUS_URL)
prom_client = PrometheusClient(PROMETHEUS_URL)
chronos_client = ChronosClient(CHRONOS_URL)
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
krr_db_client = KrrDbClient()
policy_engine = PolicyEngine()

# ==========================================
# 최근 분석 결과 캐시 (Telegram 승인 버튼 클릭 시 실제로 적용할 최종 cpu/memory 값을
# 조회하기 위한 용도). Telegram callback_data는 64바이트 제한이 있어 namespace/deployment
# 이름만 담을 수 있으므로, 실제 승인/거절 처리는 별도 서비스(alarm)가 이 엔드포인트를
# 호출해 "마지막으로 계산된 최종 권장값"을 가져가는 방식으로 동작합니다.
# ==========================================
RECOMMENDATION_TTL_SECONDS = int(os.getenv("RECOMMENDATION_TTL_SECONDS", str(24 * 3600)))  # 기본 24시간
_last_recommendations: Dict[str, Tuple[AnalysisResponse, float]] = {}


def _store_recommendation(deployment_name: str, namespace: str, response: AnalysisResponse) -> None:
    _last_recommendations[f"{namespace}/{deployment_name}"] = (response, time.monotonic())


def _get_recommendation(deployment_name: str, namespace: str) -> Optional[AnalysisResponse]:
    key = f"{namespace}/{deployment_name}"
    entry = _last_recommendations.get(key)
    if entry is None:
        return None
    response, cached_at = entry
    if time.monotonic() - cached_at > RECOMMENDATION_TTL_SECONDS:
        del _last_recommendations[key]
        return None
    return response


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """레거시 헬스체크 엔드포인트 (하위호환용). 신규 배포는 /health/live, /health/ready 사용."""
    return {"status": "ok"}


@app.get("/health/live", status_code=status.HTTP_200_OK)
def liveness_check():
    """
    Liveness Probe용: 프로세스가 살아있는지만 확인합니다 (외부 의존성 체크 없음).
    이 값이 실패하면 kubelet이 컨테이너를 재시작합니다.
    """
    return {"status": "ok"}


@app.get("/health/ready")
def readiness_check():
    """
    Readiness Probe용: 실제 트래픽을 받을 준비가 되었는지 의존성을 점검합니다.
    - MOCK_INTEGRATION=false인 경우 krr 바이너리가 PATH에 있는지 확인
    - AUTO_SEND_TELEGRAM=true인 경우 텔레그램 토큰/챗ID가 설정되어 있는지 확인
    준비되지 않았다면 503을 반환해 서비스 엔드포인트에서 트래픽을 받지 않도록 합니다.
    """
    checks = {}

    if not MOCK_INTEGRATION:
        checks["krr_binary"] = shutil.which("krr") is not None
    else:
        checks["krr_binary"] = True  # Mock 모드에서는 불필요

    if AUTO_SEND_TELEGRAM:
        checks["telegram_configured"] = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    else:
        checks["telegram_configured"] = True

    is_ready = all(checks.values())
    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks}
        )
    return {"status": "ready", "checks": checks}


async def _run_analysis(deployment_name: str, namespace: str, send_telegram: bool, krr_data: dict = None) -> AnalysisResponse:
    """
    단일 워크로드에 대한 KRR/Prometheus/Chronos-2 데이터 수집, 정책 엔진 평가,
    리포트 포맷팅, 텔레그램 발송까지 수행하는 공통 분석 로직입니다.
    /analyze(단일 대상)와 /analyze/namespace(네임스페이스 전수 분석)가 이 함수를 공유합니다.

    krr_data를 미리 전달하면(네임스페이스 전수 분석 시 이미 스캔된 결과 재사용) KRR을 다시 호출하지 않습니다.
    """
    # 1. KRR 추천 데이터 수집 (미전달 시 개별 조회)
    if krr_data is None:
        krr_data = await krr_client.get_recommendation(deployment_name, namespace)
    if not krr_data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"'{deployment_name}' (ns: {namespace})의 KRR 추천 데이터를 가져올 수 없습니다."
        )

    # KRR 응답 내부 키가 누락되어도 KeyError로 죽지 않도록 안전하게 접근
    krr_current = krr_data.get("current") or {}
    krr_recommended = krr_data.get("krr_recommended") or {}

    # Prometheus에서 직접 초기 리소스 사용량/스펙을 조회 (Prometheus 쿼리 우선 적용)
    prom_curr_spec = prom_client.get_current_resource_spec(deployment_name, namespace)
    if prom_curr_spec:
        current_cpu_val = prom_curr_spec["cpu"]
        current_mem_val = prom_curr_spec["memory"]
    else:
        current_cpu_val = krr_current.get("cpu", "0m")
        current_mem_val = krr_current.get("memory", "0Mi")

    current_spec = ResourceSpec(cpu=current_cpu_val, memory=current_mem_val)

    # KRR이 사용 이력 데이터 부족으로 권장값을 산출하지 못한 리소스는 krr_recommended.cpu/memory가 None입니다.
    # 이 경우 임의의 숫자를 지어내지 않고, 해당 리소스는 "현재값 유지"로 안전하게 처리하되
    # cpu/mem_data_insufficient 플래그를 정책 엔진에 전달해 리포트에 "데이터 부족"으로 표기되게 합니다.
    cpu_data_insufficient = krr_recommended.get("cpu") is None
    mem_data_insufficient = krr_recommended.get("memory") is None
    krr_spec = ResourceSpec(
        cpu=krr_recommended.get("cpu") or current_spec.cpu,
        memory=krr_recommended.get("memory") or current_spec.memory
    )

    # 현재 배포된 컨테이너의 limits (설정 안 돼있으면 None) - 정책 엔진이 최종 권장값을
    # 이 값 이하로 캡 걸어, Kubernetes admission 거부로 인한 조용한 무한 재시도를 방지합니다.
    krr_current_limits = krr_data.get("current_limits") or {}

    # 2. Prometheus 최근 이력 메트릭 수집 (OOM, Restart, Avg Load)
    prom_raw = prom_client.get_workload_metrics(deployment_name, namespace)
    if prom_raw is not None:
        prom_metrics = PrometheusMetrics(
            oom_killed=prom_raw.get("oom_killed", False),
            restart_count=prom_raw.get("restart_count", 0),
            avg_cpu_usage_pct=prom_raw.get("avg_cpu_usage_pct")
        )
    else:
        prom_metrics = None

    # 3. Chronos-2 예측 데이터 수집
    chronos_raw = chronos_client.get_future_forecast(deployment_name, namespace)
    if chronos_raw is not None:
        chronos_forecast = ChronosForecast(
            predicted_max_cpu_pct=chronos_raw.get("predicted_max_cpu_pct"),
            predicted_max_mem_pct=chronos_raw.get("predicted_max_mem_pct"),
            predicted_req_per_sec=chronos_raw.get("predicted_req_per_sec")
        )
    else:
        chronos_forecast = None

    # 4. 정책 엔진 평가 수행
    risk_score, overall_status, recommendations, policy_evals, cost_savings_pct = policy_engine.evaluate_optimization(
        deployment_name=deployment_name,
        namespace=namespace,
        current_res=current_spec,
        krr_res=krr_spec,
        prom_metrics=prom_metrics,
        chronos_forecast=chronos_forecast,
        cpu_data_insufficient=cpu_data_insufficient,
        mem_data_insufficient=mem_data_insufficient,
        cpu_limit_str=krr_current_limits.get("cpu"),
        memory_limit_str=krr_current_limits.get("memory")
    )

    # 5. 리소스 절감률 최종 수치 계산 (CPU / Memory)
    curr_cpu_val = parse_cpu(current_spec.cpu)
    curr_mem_val = parse_memory(current_spec.memory)

    final_cpu_val = parse_cpu(recommendations.final.cpu)
    final_mem_val = parse_memory(recommendations.final.memory)

    cpu_reduction_pct = max(0.0, ((curr_cpu_val - final_cpu_val) / curr_cpu_val) * 100.0) if curr_cpu_val > 0 else 0.0
    memory_reduction_pct = max(0.0, ((curr_mem_val - final_mem_val) / curr_mem_val) * 100.0) if curr_mem_val > 0 else 0.0

    # 6. 텔레그램 마크다운 텍스트 포맷팅 생성
    telegram_message = ReportFormatter.generate_telegram_markdown(
        deployment_name=deployment_name,
        namespace=namespace,
        cpu_reduction_pct=cpu_reduction_pct,
        memory_reduction_pct=memory_reduction_pct,
        cost_savings_pct=cost_savings_pct,
        risk_score=risk_score,
        overall_status=overall_status,
        recommendations=recommendations,
        policy_evaluations=policy_evals
    )

    # 7. 텔레그램 Direct 메시지 전송 처리 (요청 또는 환경변수 설정 시)
    telegram_sent = False
    if send_telegram or AUTO_SEND_TELEGRAM:
        telegram_sent = telegram_client.send_report(
            telegram_message,
            overall_status,
            deployment_name=deployment_name,
            namespace=namespace
        )

    # 7-2. KRR 분석 결과를 CNPG DB (krr_logs 테이블)에 저장
    krr_db_client.save_log(
        namespace=namespace,
        deployment_name=deployment_name,
        cpu_current=current_spec.cpu,
        cpu_recommended=recommendations.final.cpu,
        mem_current=current_spec.memory,
        mem_recommended=recommendations.final.memory
    )

    # 8. 응답 빌드
    result = AnalysisResponse(
        deployment_name=deployment_name,
        namespace=namespace,
        cpu_reduction_pct=round(cpu_reduction_pct, 1),
        memory_reduction_pct=round(memory_reduction_pct, 1),
        cost_savings_pct=round(cost_savings_pct, 1),
        risk_score=risk_score,
        overall_status=overall_status,
        recommendations=recommendations,
        policy_evaluations=policy_evals,
        telegram_message=telegram_message,
        telegram_sent=telegram_sent
    )

    # 9. Telegram 승인 버튼 클릭 시(alarm 서비스가 /recommendation을 조회) 실제로 적용할
    # 최종 값을 알 수 있도록 최근 결과를 캐시에 저장
    _store_recommendation(deployment_name, namespace, result)

    return result


@app.get("/recommendation/{namespace}/{deployment_name}")
def get_last_recommendation(namespace: str, deployment_name: str):
    """
    가장 최근 /analyze(또는 /analyze/namespace) 실행에서 계산된 최종 권장 리소스를 조회합니다.

    Telegram 승인 버튼의 callback_data(`infra_approve:{namespace}:{deployment_name}`)는
    64바이트 제한 때문에 실제 cpu/memory 값을 담지 못합니다. 그래서 운영자가 승인 버튼을 누르면
    alarm 서비스가 이 엔드포인트를 호출해 "마지막으로 계산된 최종 권장값"을 가져간 뒤
    GitOps 파이프라인에 그 값을 실어 보냅니다.
    """
    cached = _get_recommendation(deployment_name, namespace)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{deployment_name}' (ns: {namespace})의 최근 분석 결과가 없거나 {RECOMMENDATION_TTL_SECONDS}초 TTL이 만료되었습니다. /analyze를 다시 실행해주세요."
        )
    if cached.overall_status != "PASS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"최근 분석 결과가 PASS 상태가 아니어서(overall_status={cached.overall_status}) 적용할 수 없습니다."
        )

    return {
        "namespace": namespace,
        "deployment_name": deployment_name,
        "final_cpu": cached.recommendations.final.cpu,
        "final_memory": cached.recommendations.final.memory,
        "overall_status": cached.overall_status,
        "risk_score": cached.risk_score
    }


@app.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_workload(request: AnalysisRequest):
    """
    지정된 워크로드의 리소스 할당을 분석하여 정책 엔진 보정 결과를 생성하고 텔레그램 알림을 처리합니다.
    """
    logger.info(f"Received analysis request: {request.deployment_name} in namespace '{request.namespace}' (send_telegram={request.send_telegram})")

    try:
        return await _run_analysis(request.deployment_name, request.namespace, request.send_telegram)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"분석 수행 도중 서버 내부 에러가 발생했습니다: {str(e)}"
        )


@app.post("/analyze/namespace", response_model=NamespaceAnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_namespace(request: NamespaceAnalysisRequest):
    """
    네임스페이스 내 KRR이 발견한 모든 워크로드를 전수 분석합니다.
    KRR CLI는 -n <namespace> 실행 시 이미 네임스페이스 전체를 스캔하므로, 이를 한 번만 실행하고
    발견된 각 워크로드에 대해 Prometheus/Chronos-2 조회 및 정책 평가를 개별 수행합니다.
    CronJob에서 targetDeployment 하나만 호출하던 기존 한계를 해소하기 위한 엔드포인트입니다.
    """
    logger.info(f"Received namespace-wide analysis request: namespace='{request.namespace}' (send_telegram={request.send_telegram})")

    namespace_scan = await krr_client.get_namespace_recommendations(request.namespace)
    if not namespace_scan:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"네임스페이스 '{request.namespace}'에서 KRR이 발견한 워크로드가 없습니다."
        )

    results = []
    for deployment_name, krr_data in namespace_scan.items():
        try:
            result = await _run_analysis(deployment_name, request.namespace, request.send_telegram, krr_data=krr_data)
            results.append(result)
        except Exception as e:
            # 워크로드 하나의 분석 실패가 전체 네임스페이스 분석을 중단시키지 않도록 함
            logger.error(f"'{deployment_name}' 분석 중 오류 발생, 건너뜁니다: {str(e)}", exc_info=True)

    return NamespaceAnalysisResponse(
        namespace=request.namespace,
        analyzed_count=len(results),
        results=results
    )
