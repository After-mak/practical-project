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
    """CPU 문자열(예: 1000m, 1, 0.5, 2e3m)을 코어 수(float)로 안전하게 파싱합니다.
    인식할 수 없는 형식이 들어와도 예외를 던지지 않고 0.0으로 안전하게 대체합니다
    (KRR/Prometheus가 예상치 못한 포맷을 반환해도 API가 500으로 죽지 않도록 함)."""
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str).strip().lower()
    try:
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000.0
        return float(cpu_str)
    except ValueError:
        logger.warning(f"[parse_cpu] 인식할 수 없는 CPU 포맷 '{cpu_str}', 0으로 대체합니다.")
        return 0.0

def parse_memory(mem_str: str) -> float:
    """메모리 문자열(예: 2Gi, 2G, 512Mi, 512M, 1024K, 2147483648, 2e9)을 MiB 단위(float)로 안전하게 파싱합니다.
    Ki/Mi/Gi/Ti(이진 단위), K/M/G/T(십진 단위), 지수 표기, 순수 바이트 정수까지 모두 커버하며,
    인식할 수 없는 형식은 예외 대신 0.0으로 대체해 API가 500으로 죽지 않도록 합니다."""
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*([a-zA-Z]*)$", mem_str)
    if not match:
        logger.warning(f"[parse_memory] 인식할 수 없는 메모리 포맷 '{mem_str}', 0으로 대체합니다.")
        return 0.0

    value, unit = match.groups()
    try:
        val = float(value)
    except ValueError:
        logger.warning(f"[parse_memory] 숫자로 변환할 수 없는 메모리 값 '{value}', 0으로 대체합니다.")
        return 0.0

    unit_lower = unit.lower()
    if unit_lower in ('ti', 't'):
        return val * 1024.0 * 1024.0
    elif unit_lower in ('gi', 'g'):
        return val * 1024.0
    elif unit_lower in ('mi', 'm'):
        return val
    elif unit_lower in ('ki', 'k'):
        return val / 1024.0
    elif unit_lower in ('b', ''):
        return val / (1024.0 * 1024.0)  # 단위가 없으면 바이트로 가정 (Prometheus 원시 메트릭 대응)
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
        chronos_forecast: Optional[ChronosForecast],
        cpu_data_insufficient: bool = False,
        mem_data_insufficient: bool = False,
        cpu_limit_str: Optional[str] = None,
        memory_limit_str: Optional[str] = None
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

        cpu_limit = parse_cpu(cpu_limit_str) if cpu_limit_str else None
        memory_limit = parse_memory(memory_limit_str) if memory_limit_str else None

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

        # 정책 7: KRR 데이터 충분성 검사
        # KRR은 사용 이력 데이터가 부족하면 권장값 대신 '?'(미확정)를 반환합니다. 이 경우 krr_res에는
        # 이미 상위 계층(main.py)에서 현재값이 그대로 채워져 들어오므로(임의의 숫자로 추측하지 않음),
        # RULE_01/02의 감축률 계산은 자연스럽게 0%로 나와 해당 리소스가 안전하게 유지됩니다.
        # 여기서는 그 이유를 리포트에 명시적으로 알려주기 위한 안내성 경고만 추가합니다.
        if cpu_data_insufficient or mem_data_insufficient:
            score += 10
            insufficient_parts = []
            if cpu_data_insufficient:
                insufficient_parts.append("CPU")
            if mem_data_insufficient:
                insufficient_parts.append("Memory")
            policy_evals.append(PolicyResult(
                rule_id="RULE_07",
                name="KRR 데이터 충분성 검사",
                status="WARN",
                description=f"{'/'.join(insufficient_parts)} 사용 이력 데이터가 부족하여 KRR이 권장값을 산출하지 못했습니다. 해당 리소스는 임의로 추정하지 않고 현재 설정을 유지합니다."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_07",
                name="KRR 데이터 충분성 검사",
                status="PASS",
                description="KRR이 CPU/Memory 모두 충분한 사용 이력 데이터를 기반으로 권장값을 산출했습니다."
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

        # 정책 8: 컨테이너 limits 초과 방지
        # Kubernetes는 requests가 limits보다 큰 Deployment를 admission 단계에서 거부한다.
        # 위 정책들이 계산한 final 값이 실제 배포된 limits를 넘으면, GitOps에 반영될 때 조용히
        # 계속 실패(무한 재시도)하는 대신 여기서 limits 이하로 캡을 걸어 애초에 유효한 값만 내보낸다.
        capped_by_limits = False
        if cpu_limit is not None and cpu_limit > 0 and final_cpu > cpu_limit:
            final_cpu = cpu_limit
            capped_by_limits = True
        if memory_limit is not None and memory_limit > 0 and final_mem > memory_limit:
            final_mem = memory_limit
            capped_by_limits = True

        if capped_by_limits:
            policy_evals.append(PolicyResult(
                rule_id="RULE_08",
                name="컨테이너 limits 초과 방지",
                status="WARN",
                description="정책 검증을 거친 권장값이 배포된 컨테이너의 limits를 초과하여, Kubernetes가 반영을 거부하지 않도록 limits 이하로 자동 조정했습니다."
            ))
        elif cpu_limit is not None or memory_limit is not None:
            policy_evals.append(PolicyResult(
                rule_id="RULE_08",
                name="컨테이너 limits 초과 방지",
                status="PASS",
                description="최종 권장값이 컨테이너 limits 이내입니다."
            ))
        else:
            policy_evals.append(PolicyResult(
                rule_id="RULE_08",
                name="컨테이너 limits 초과 방지",
                status="WARN",
                description="배포된 컨테이너의 limits 정보를 확인하지 못해 초과 여부를 검증하지 못했습니다."
            ))

        recommendations = RecommendationData(
            current=current_res,
            krr=krr_res,
            final=ResourceSpec(
                cpu=format_cpu(final_cpu),
                memory=format_memory(final_mem)
            ),
            krr_cpu_data_insufficient=cpu_data_insufficient,
            krr_memory_data_insufficient=mem_data_insufficient
        )
        
        # --- 예상 비용 변화율 계산 ---
        # 부호 있는 값으로 계산합니다: 양수 = 비용 절감, 음수 = 비용 증가.
        # Chronos-2 예측(RULE_05)으로 인해 스펙이 오히려 상향된 경우, 이를 0%로 뭉개면
        # 운영자가 비용 증가 상황을 인지하지 못하므로 절대 max(0.0, ...)로 클램핑하지 않습니다.
        current_cost = (curr_cpu * CPU_UNIT_COST) + ((curr_mem / 1024.0) * MEM_UNIT_COST)
        final_cost = (final_cpu * CPU_UNIT_COST) + ((final_mem / 1024.0) * MEM_UNIT_COST)

        if overall_status == "FAIL" or current_cost <= 0:
            cost_change_pct = 0.0
        else:
            cost_change_pct = ((current_cost - final_cost) / current_cost) * 100.0

        return risk_score, overall_status, recommendations, policy_evals, round(cost_change_pct, 1)
