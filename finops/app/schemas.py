from pydantic import BaseModel, Field
from typing import List, Optional

# 1. 최적화를 요청할 대상 워크로드 스키마
class AnalysisRequest(BaseModel):
    deployment_name: str = Field(default="payment-api", description="최적화 대상 Deployment 이름")
    namespace: str = Field(default="prod", description="쿠버네티스 네임스페이스")
    container_name: Optional[str] = Field(default=None, description="최적화 대상 컨테이너 이름")
    history_duration: str = Field(default="336h", description="KRR 분석 이력 범위(예: 24h, 7d)")
    send_telegram: bool = Field(default=False, description="분석 후 텔레그램 승인 요청 메시지 다이렉트 전송 여부")

# 1-1. 네임스페이스 내 전체 워크로드를 한 번에 분석 요청하는 스키마 (CronJob 다중 타겟팅용)
class NamespaceAnalysisRequest(BaseModel):
    namespace: str = Field(default="prod", description="전수 분석할 쿠버네티스 네임스페이스")
    history_duration: str = Field(default="336h", description="KRR 분석 이력 범위(예: 24h, 7d)")
    send_telegram: bool = Field(default=False, description="분석 후 텔레그램 승인 요청 메시지 다이렉트 전송 여부")

# 2. CPU/메모리 리소스 규격 정의
class ResourceSpec(BaseModel):
    cpu: str = Field(..., description="CPU 요청량 (예: 1000m, 500m)")
    memory: str = Field(..., description="메모리 요청량 (예: 2Gi, 512Mi)")

# 3. 비교 리포트에 담을 3단계 리소스 권장안 정보
class RecommendationData(BaseModel):
    current: ResourceSpec = Field(..., description="현재 설정되어 있는 Request 값")
    krr: ResourceSpec = Field(..., description="KRR 오픈소스가 추천한 원래 값 (데이터 부족 시 현재값과 동일하게 채워짐)")
    final: ResourceSpec = Field(..., description="정책 엔진 검증을 거친 최종 승인 권장값")
    krr_cpu_data_insufficient: bool = Field(default=False, description="KRR이 CPU 권장값을 산출할 만큼 충분한 사용 이력 데이터가 없었는지 여부")
    krr_memory_data_insufficient: bool = Field(default=False, description="KRR이 Memory 권장값을 산출할 만큼 충분한 사용 이력 데이터가 없었는지 여부")

# 4. 개별 정책 검증 항목 결과 정의
class PolicyResult(BaseModel):
    rule_id: str = Field(..., description="정책 아이디 (예: RULE_01)")
    name: str = Field(..., description="정책 이름")
    status: str = Field(..., description="검증 결과 (PASS / FAIL / WARN)")
    description: str = Field(..., description="상세 위반 사유 또는 경고 메시지")

# 5. 프로메테우스에서 정제한 지표 스키마
class PrometheusMetrics(BaseModel):
    oom_killed: bool = Field(default=False, description="최근 OOM킬 발생 여부")
    restart_count: int = Field(default=0, description="최근 Pod 재시작 횟수")
    avg_cpu_usage_pct: Optional[float] = Field(default=None, description="최근 평균 CPU 사용률 (%)")
    throttled: bool = Field(default=False, description="최근 24시간 내 CPU Throttling 발생 여부")

# 6. Chronos-2 예측 데이터 스키마
class ChronosForecast(BaseModel):
    predicted_max_cpu_pct: Optional[float] = Field(default=None, description="향후 10분 내 예측 CPU 최대치 (%)")
    predicted_max_mem_pct: Optional[float] = Field(default=None, description="향후 10분 내 예측 메모리 최대치 (%)")
    predicted_req_per_sec: Optional[float] = Field(default=None, description="향후 10분 내 예측 초당 요청 수 (req/s)")

# 7. 최종 분석 결과 및 텔레그램 연동을 위한 응답 스키마
class AnalysisResponse(BaseModel):
    deployment_name: str = Field(..., description="대상 Deployment 이름")
    namespace: str = Field(..., description="대상 Namespace")
    container_name: str = Field(..., description="대상 Container")
    
    # 리소스 및 비용 절감 지표
    cpu_reduction_pct: float = Field(..., description="최종 CPU 절감률 (%)")
    memory_reduction_pct: float = Field(..., description="최종 메모리 절감률 (%)")
    cost_savings_pct: float = Field(..., description="예상 비용 변화율 (%). 양수는 절감, 음수는 비용 증가를 의미합니다.")
    
    # 위험 평가 및 상태
    risk_score: str = Field(..., description="종합 위험 등급 (SAFE / MEDIUM / HIGH)")
    overall_status: str = Field(..., description="전체 정책 통과 여부 (PASS / FAIL)")
    
    # 상세 데이터 
    recommendations: RecommendationData = Field(..., description="구간별 리소스 스펙 데이터")
    policy_evaluations: List[PolicyResult] = Field(default=[], description="수행한 정책 검증 결과 목록")
    
    # 텔레그램 메시지 연동용 포맷 텍스트 및 전송 상태
    telegram_message: str = Field(..., description="텔레그램 전송을 위해 포맷팅된 텍스트 메시지")
    telegram_sent: bool = Field(default=False, description="텔레그램 Direct 메시지 발송 여부")

# 8. 네임스페이스 전체 분석 응답 스키마
class NamespaceAnalysisResponse(BaseModel):
    namespace: str = Field(..., description="분석한 Namespace")
    analyzed_count: int = Field(..., description="분석에 성공한 워크로드 수")
    results: List[AnalysisResponse] = Field(default=[], description="워크로드별 분석 결과 목록")
