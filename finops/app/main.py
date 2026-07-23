import os
import logging
from fastapi import FastAPI, HTTPException, status
from app.schemas import AnalysisRequest, AnalysisResponse, ResourceSpec, PrometheusMetrics, ChronosForecast
from app.clients import KrrClient, PrometheusClient, ChronosClient, TelegramClient
from app.engine import PolicyEngine, parse_cpu, parse_memory
from app.formatter import ReportFormatter

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI 기반 FinOps 정책 분석 엔진 API",
    description="KRR 추천값 및 Prometheus/Chronos-2 메트릭을 분석하여 최적의 안전 리소스 권장안을 생성하고 텔레그램 승인 알림을 발송하는 정책 엔진 API",
    version="1.2.0"
)

# API 엔드포인트 URL 및 텔레그램 설정 (환경변수 참조)
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.monitoring.svc.cluster.local:9090")
CHRONOS_URL = os.getenv("CHRONOS_URL", "http://chronos-model.monitoring.svc.cluster.local:8000")
KRR_URL = os.getenv("KRR_URL", "http://krr.monitoring.svc.cluster.local:8080")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 클라이언트 인스턴스화
krr_client = KrrClient(KRR_URL)
prom_client = PrometheusClient(PROMETHEUS_URL)
chronos_client = ChronosClient(CHRONOS_URL)
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
policy_engine = PolicyEngine()

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    EKS 파드 헬스체크(Liveness/Readiness Probe)용 엔드포인트
    """
    return {"status": "ok"}

@app.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_workload(request: AnalysisRequest):
    """
    지정된 워크로드의 리소스 할당을 분석하여 정책 엔진 보정 결과를 생성하고 텔레그램 알림을 처리합니다.
    """
    logger.info(f"Received analysis request: {request.deployment_name} in namespace '{request.namespace}' (send_telegram={request.send_telegram})")
    
    try:
        # 1. KRR 추천 데이터 및 Prometheus 기반 초기 사용량 수집
        krr_data = krr_client.get_recommendation(request.deployment_name, request.namespace)
        if not krr_data:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="KRR 추천 데이터를 가져올 수 없습니다."
            )

        # Prometheus에서 직접 초기 리소스 사용량/스펙을 조회 (Prometheus 쿼리 우선 적용)
        prom_curr_spec = prom_client.get_current_resource_spec(request.deployment_name, request.namespace)
        if prom_curr_spec:
            current_cpu_val = prom_curr_spec["cpu"]
            current_mem_val = prom_curr_spec["memory"]
        else:
            current_cpu_val = krr_data["current"]["cpu"]
            current_mem_val = krr_data["current"]["memory"]

        current_spec = ResourceSpec(
            cpu=current_cpu_val,
            memory=current_mem_val
        )
        krr_spec = ResourceSpec(
            cpu=krr_data["krr_recommended"]["cpu"],
            memory=krr_data["krr_recommended"]["memory"]
        )
        
        # 2. Prometheus 최근 이력 메트릭 수집 (OOM, Restart, Avg Load)
        prom_raw = prom_client.get_workload_metrics(request.deployment_name, request.namespace)
        if prom_raw is not None:
            prom_metrics = PrometheusMetrics(
                oom_killed=prom_raw.get("oom_killed", False),
                restart_count=prom_raw.get("restart_count", 0),
                avg_cpu_usage_pct=prom_raw.get("avg_cpu_usage_pct")
            )
        else:
            prom_metrics = None
        
        # 3. Chronos-2 예측 데이터 수집
        chronos_raw = chronos_client.get_future_forecast(request.deployment_name, request.namespace)
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
            deployment_name=request.deployment_name,
            namespace=request.namespace,
            current_res=current_spec,
            krr_res=krr_spec,
            prom_metrics=prom_metrics,
            chronos_forecast=chronos_forecast
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
            deployment_name=request.deployment_name,
            namespace=request.namespace,
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
        if request.send_telegram or os.getenv("AUTO_SEND_TELEGRAM", "false").lower() == "true":
            telegram_sent = telegram_client.send_report(
                telegram_message,
                overall_status,
                deployment_name=request.deployment_name,
                namespace=request.namespace
            )
        
        # 8. 응답 빌드
        return AnalysisResponse(
            deployment_name=request.deployment_name,
            namespace=request.namespace,
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
        
    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"분석 수행 도중 서버 내부 에러가 발생했습니다: {str(e)}"
        )
