import re
import logging
from typing import Tuple, List, Optional
from app.schemas import ResourceSpec, RecommendationData, PolicyResult, PrometheusMetrics, ChronosForecast

logger = logging.getLogger(__name__)

# AWS 단가 기준 (대략적인 온프레미스/클라우드 기준값)
# 1 vCPU 코어당 월 약 $25
# 1 GiB 메모리당 월 약 $4
CPU_UNIT_COST = 25.0
MEM_UNIT_COST = 4.0

def parse_cpu(cpu_str: str) -> float:
    """CPU 문자열(예: 1000m, 1, 0.5, 500M)을 코어 수(float)로 안전하게 파싱합니다."""
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str).strip().lower()
    if cpu_str.endswith('m'):
        return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)

def parse_memory(mem_str: str) -> float:
    """메모리 문자열(예: 2Gi, 2G, 512Mi, 512M, 1024K)을 MiB 단위(float)로 안전하게 파싱합니다."""
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip()
    match = re.match(r"^([0-9.]+)\s*([a-zA-Z]*)$", mem_str)
    if not match:
        raise ValueError(f"Invalid memory format: {mem_str}")
    value, unit = match.groups()
    val = float(value)
    unit_lower = unit.lower()
    
    if unit_lower in ('gi', 'g'):
        return val * 1024.0
    elif unit_lower in ('mi', 'm'):
        return val
    elif unit_lower in ('ki', 'k'):
        return val / 1024.0
    elif unit_lower in ('b', ''):
        return val / (1024.0 * 1024.0)  # 기본 바이트 단위로 가정
    return val / (1024.0 * 1024.0)

def format_cpu(cores: float) -> str:
    """Float 코어 수를 쿠버네티스 포맷 문자열로 변환합니다."""
    if cores < 1.0:
        return f"{int(round(cores * 1000))}m"
    return f"{round(cores, 2)}"

def format_memory(mib: float) -> str:
    """Float MiB 값을 쿠버네티스 포맷 문자열로 변환합니다. (K8s는 메모리 소수점을 허용하지 않으므로 정수로 반환)"""
    if mib >= 1024.0 and mib % 1024.0 == 0:
        return f"{int(mib / 1024.0)}Gi"
    return f"{int(round(mib))}Mi"

class PolicyEngine:
    def __init__(self):
        pass

    def evaluate_optimization(
        self,
        deployment_name: str,
        namespace: str,
        current_res: ResourceSpec,
        krr_res: ResourceSpec,
        prom_metrics: Optional[PrometheusMetrics],
        chronos_forecast: Optional[ChronosForecast]
    ) -> Tuple[str, str, RecommendationData, List[PolicyResult], float]:
        """
        KRR 추천 및 모니터링 메트릭을 기반으로 운영 정책을 적용하고 
        위험도(Risk Score)와 최종 안전 승인값을 도출합니다.
        """
        
        # 1. 리소스 단위 파싱
        curr_cpu = parse_cpu(current_res.cpu)
        curr_mem = parse_memory(current_res.memory)
        
        krr_cpu = parse_cpu(krr_res.cpu)
        krr_mem = parse_memory(krr_res.memory)
        
        # 기본적으로는 KRR 추천값을 최종 추천값의 후보로 지정
        final_cpu = krr_cpu
        final_mem = krr_mem
        
        score = 0
        policy_evals = []
        
        # --- 정책 검증 로직 시작 ---
        
        # 정책 1: 급격한 CPU 감소 정책 (CPU 감소율 50% 이상 제한)
        cpu_reduction = (curr_cpu - krr_cpu) / curr_cpu if curr_cpu > 0 else 0
        if cpu_reduction >= 0.5:
            score += 25
            # 완화 조치: 급격한 감축 방지를 위해 원래 리소스의 70% 수준으로 보정
            final_cpu = curr_cpu * 0.7
            policy_evals.append(PolicyResult(
                rule_id="RULE_01",
                name="과도한 CPU 감축 제한",
                status="WARN",
                description=f"KRR 추천 CPU 감소율({round(cpu_reduction*100, 1)}%)이 50%를 초과하여 안전 마진을 위해 최종 권장값을 완화 조정(원래의 70% 설정)함."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_01",
                name="과도한 CPU 감축 제한",
                status="PASS",
                description="CPU 감축 제안 비율이 안전 범위 내에 있습니다."
            ))

        # 정책 2: 급격한 Memory 감소 정책 (Memory 감소율 60% 이상 제한)
        mem_reduction = (curr_mem - krr_mem) / curr_mem if curr_mem > 0 else 0
        if mem_reduction >= 0.6:
            score += 20
            # 완화 조치: 급격한 메모리 다이어트 방지를 위해 원래 리소스의 60% 수준으로 보정
            final_mem = curr_mem * 0.6
            policy_evals.append(PolicyResult(
                rule_id="RULE_02",
                name="과도한 메모리 감축 제한",
                status="WARN",
                description=f"KRR 추천 메모리 감소율({round(mem_reduction*100, 1)}%)이 60%를 초과하여 최종 권장값을 완화 조정(원래의 60% 설정)함."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_02",
                name="과도한 메모리 감축 제한",
                status="PASS",
                description="메모리 감축 제안 비율이 안전 범위 내에 있습니다."
            ))

        # 정책 3: OOM킬 발생 여부 정책 (OOM킬 발생 시 최적화 실패 처리)
        if prom_metrics is not None and prom_metrics.oom_killed:
            score += 60
            # 조치: 리소스 최적화(감축)를 전면 반려하고 현재(Current) 리소스를 유지하도록 강제 설정
            final_cpu = curr_cpu
            final_mem = curr_mem
            policy_evals.append(PolicyResult(
                rule_id="RULE_03",
                name="OOM 발생 여부 검사",
                status="FAIL",
                description="최근 워크로드에서 OOM(Out of Memory) 킬이 감지되었습니다. 안전을 위해 최적화 적용을 전면 반려하고 현재 리소스를 유지합니다."
            ))
        elif prom_metrics is None:
            score += 15
            policy_evals.append(PolicyResult(
                rule_id="RULE_03",
                name="OOM 발생 여부 검사",
                status="WARN",
                description="Prometheus OOM 이력 메트릭을 수집하지 못해 경고 마진을 적용합니다."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_03",
                name="OOM 발생 여부 검사",
                status="PASS",
                description="최근 OOM킬 발생 이력이 없습니다."
            ))

        # 정책 4: 최근 Restart 증가 정책 (비정상 재시작 10회 이상 시 실패 처리)
        if prom_metrics is not None and prom_metrics.restart_count >= 10:
            score += 50
            # 조치: 최적화 보류 및 현재 스펙 유지
            final_cpu = curr_cpu
            final_mem = curr_mem
            policy_evals.append(PolicyResult(
                rule_id="RULE_04",
                name="잦은 Pod 재시작 검사",
                status="FAIL",
                description=f"최근 Pod 재시작 횟수가 {prom_metrics.restart_count}회 발생하여 불안정합니다. 리소스 감축 최적화 적용을 보류합니다."
            ))
        elif prom_metrics is None:
            score += 15
            policy_evals.append(PolicyResult(
                rule_id="RULE_04",
                name="잦은 Pod 재시작 검사",
                status="WARN",
                description="Prometheus Pod 재시작 횟수 메트릭을 수집하지 못했습니다."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_04",
                name="잦은 Pod 재시작 검사",
                status="PASS",
                description=f"재시작 횟수({prom_metrics.restart_count}회)가 기준치 미만으로 양호합니다."
            ))

        # 정책 5: Chronos-2 예측 부하 반영 (향후 10분 내 CPU 부하 80% 이상 예측 시 최적화 제한 및 상향)
        if chronos_forecast is not None and chronos_forecast.predicted_max_cpu_pct is not None:
            if chronos_forecast.predicted_max_cpu_pct >= 80.0:
                score += 45
                # KEDA가 Chronos를 기반으로 HPA(파드 개수 스케일아웃)를 수행할 예정이므로,
                # 파드 개별 스펙(수직)까지 Scale-Up 하면 이중 스케일링으로 비용이 낭비됩니다.
                # 따라서 스펙 감축만 취소(현재 스펙 유지)하고 HPA에 확장을 위임합니다.
                final_cpu = curr_cpu
                policy_evals.append(PolicyResult(
                    rule_id="RULE_05",
                    name="Chronos-2 미래 부하 예측 검사",
                    status="WARN",
                    description=f"향후 10분 내 예측 부하가 {chronos_forecast.predicted_max_cpu_pct}%로 급증합니다. KEDA의 안전한 파드 스케일아웃(HPA)을 방해하지 않도록 스펙 감축을 보류하고 현재 CPU를 유지합니다."
                ))
            else:
                policy_evals.append(PolicyResult(
                    rule_id="RULE_05",
                    name="Chronos-2 미래 부하 예측 검사",
                    status="PASS",
                    description=f"향후 10분 내 예상 CPU 최대 로드({chronos_forecast.predicted_max_cpu_pct}%)가 안정 범위에 있어 감축 적용이 가능합니다."
                ))
        else:
            score += 30
            final_cpu = max(final_cpu, curr_cpu * 0.85)
            policy_evals.append(PolicyResult(
                rule_id="RULE_05",
                name="Chronos-2 미래 부하 예측 검사",
                status="WARN",
                description="Chronos-2 시계열 예측 메트릭을 수집하지 못했습니다. 안전을 위해 감축 마진을 보수적으로 제한(기존 리소스의 85% 이상 유지)합니다."
            ))

        # 정책 6: 평균 CPU 로드 안정성 체크
        if prom_metrics is not None and prom_metrics.avg_cpu_usage_pct is not None and prom_metrics.avg_cpu_usage_pct < 20.0 and not prom_metrics.oom_killed:
            score = max(0, score - 15)
            policy_evals.append(PolicyResult(
                rule_id="RULE_06",
                name="평균 부하 안정성 검사",
                status="PASS",
                description=f"최근 평균 CPU 사용량({prom_metrics.avg_cpu_usage_pct}%)이 20% 미만으로 매우 안정적이므로 감축 최적화 수행을 적극 권장합니다."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_06",
                name="평균 부하 안정성 검사",
                status="PASS",
                description="일반적인 부하 프로필을 갖고 있거나 메트릭 미수집으로 표준 기준을 적용합니다."
            ))

        # --- 위험도 및 전체 PASS/FAIL 판정 ---
        if score >= 70:
            risk_score = "HIGH"
            overall_status = "FAIL"
        elif score >= 35:
            risk_score = "MEDIUM"
            overall_status = "PASS"
        else:
            risk_score = "SAFE"
            overall_status = "PASS"
            
        # 전체 상태가 FAIL인 경우, 최종 권장 리소스를 현재 수준으로 원복
        if overall_status == "FAIL":
            final_cpu = curr_cpu
            final_mem = curr_mem
            
        recommendations = RecommendationData(
            current=current_res,
            krr=krr_res,
            final=ResourceSpec(
                cpu=format_cpu(final_cpu),
                memory=format_memory(final_mem)
            )
        )
        
        # --- 예상 비용 절감률 계산 ---
        current_cost = (curr_cpu * CPU_UNIT_COST) + ((curr_mem / 1024.0) * MEM_UNIT_COST)
        final_cost = (final_cpu * CPU_UNIT_COST) + ((final_mem / 1024.0) * MEM_UNIT_COST)
        
        if overall_status == "FAIL" or current_cost <= 0:
            cost_savings_pct = 0.0
        else:
            cost_savings_pct = max(0.0, ((current_cost - final_cost) / current_cost) * 100.0)
            
        return risk_score, overall_status, recommendations, policy_evals, round(cost_savings_pct, 1)
