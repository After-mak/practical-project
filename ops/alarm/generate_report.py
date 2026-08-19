#!/usr/bin/env python3
"""
Chronos-2 예측 결과를 읽어서 finops_report.md를 실제 데이터로 생성하는 스크립트
KRR 임계값 단계(loose/medium/tight)는 기본적으로 시간 경과에 따라 자동 승급되며,
KRR_STAGE 환경변수를 명시적으로 지정하면 수동 모드로 동작합니다(테스트용).
KEDA ScaledObject의 실제 상태(활성 여부, 현재 replica 수)도 조회해서 리포트에 반영합니다.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

FORECAST_FILE = os.environ.get("FORECAST_FILE", os.path.expanduser("~/k8s-manifest/forecast_result.json"))
REPORT_FILE = os.environ.get("REPORT_FILE", os.path.expanduser("~/practical-project/finops_report.md"))
STATE_FILE = os.environ.get("KRR_STATE_FILE", os.path.expanduser("~/k8s-manifest/krr_stage_state.json"))

LOOSE_TO_MEDIUM_DAYS = int(os.environ.get("KRR_LOOSE_DAYS", "14"))
MEDIUM_TO_TIGHT_DAYS = int(os.environ.get("KRR_MEDIUM_DAYS", "14"))

KEDA_SCALEDOBJECT_NAME = os.environ.get("KEDA_SCALEDOBJECT_NAME", "finops-tg-scaler")
KEDA_NAMESPACE = os.environ.get("KEDA_NAMESPACE", "default")

STAGE_DESC = {
    "loose":  "CPU 감소 최대 50% 제한 (초기 느슨한 단계)",
    "medium": "CPU 감소 최대 30% 제한 (중간 단계)",
    "tight":  "CPU 감소 최대 10% 제한 (안정화 단계)",
}
STAGE_ORDER = ["loose", "medium", "tight"]


def load_forecast():
    with open(FORECAST_FILE) as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"stage": "loose", "since": datetime.now(timezone.utc).isoformat()}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def resolve_stage():
    """KRR_STAGE가 명시적으로 지정되면 수동 모드, 아니면 상태 파일 기반 자동 승급."""
    manual_stage = os.environ.get("KRR_STAGE")
    if manual_stage:
        return manual_stage, None, None

    state = load_state()
    stage = state.get("stage", "loose")
    since = datetime.fromisoformat(state.get("since"))
    elapsed_days = (datetime.now(timezone.utc) - since).days

    threshold = None
    if stage == "loose":
        threshold = LOOSE_TO_MEDIUM_DAYS
    elif stage == "medium":
        threshold = MEDIUM_TO_TIGHT_DAYS

    if threshold is not None and elapsed_days >= threshold:
        stage = STAGE_ORDER[STAGE_ORDER.index(stage) + 1]
        since = datetime.now(timezone.utc)
        elapsed_days = 0
        save_state({"stage": stage, "since": since.isoformat()})
    elif not os.path.exists(STATE_FILE):
        save_state({"stage": stage, "since": since.isoformat()})

    remaining = None
    if stage == "loose":
        remaining = LOOSE_TO_MEDIUM_DAYS - elapsed_days
    elif stage == "medium":
        remaining = MEDIUM_TO_TIGHT_DAYS - elapsed_days

    return stage, elapsed_days, remaining


def get_keda_status():
    """KEDA ScaledObject/HPA 상태를 조회해서 사람이 읽을 수 있는 문구로 반환.
    클러스터 미연결/미배포 시 안전하게 안내 문구로 대체한다."""
    try:
        so_result = subprocess.run(
            ["kubectl", "get", "scaledobject", KEDA_SCALEDOBJECT_NAME, "-n", KEDA_NAMESPACE, "-o", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if so_result.returncode != 0:
            return "확인 불가 (KEDA ScaledObject 미배포 또는 클러스터 미연결)"

        so_data = json.loads(so_result.stdout)
        conditions = so_data.get("status", {}).get("conditions", [])
        active = any(c.get("type") == "Active" and c.get("status") == "True" for c in conditions)

        hpa_name = f"keda-hpa-{KEDA_SCALEDOBJECT_NAME}"
        hpa_result = subprocess.run(
            ["kubectl", "get", "hpa", hpa_name, "-n", KEDA_NAMESPACE, "-o", "json"],
            capture_output=True, text=True, timeout=5,
        )
        current_replicas = None
        if hpa_result.returncode == 0:
            hpa_data = json.loads(hpa_result.stdout)
            current_replicas = hpa_data.get("status", {}).get("currentReplicas")

        state_text = "활성(Active)" if active else "대기 중(Inactive)"
        replica_text = f", 현재 {current_replicas}개 replica 운영 중" if current_replicas is not None else ""
        return f"KEDA {state_text}{replica_text}"
    except Exception as e:
        return f"확인 불가 ({e})"


def build_report(forecast, stage, elapsed_days, remaining_days, keda_status):
    current = forecast["current_replicas"]
    predicted = forecast["predicted_replicas"]
    cpu_usage = forecast["predicted_cpu_usage"]
    scale_out = forecast["scale_out_needed"]
    timestamp = forecast.get("timestamp", "N/A")
    if current > 0 and predicted < current:
        pct = round((1 - predicted / current) * 100, 1)
        cost_line = f"- 예상 비용 절감율: 온디맨드 대비 약 {pct}% 절감 가능"
    elif current > 0 and predicted > current:
        pct = round((predicted / current - 1) * 100, 1)
        cost_line = f"- 예상 비용 증가율: 온디맨드 대비 약 {pct}% 증가 예상 (스케일아웃 필요)"
    else:
        cost_line = "- 예상 비용 변화: 없음 (현재 replica 수 유지)"

    stage_line = STAGE_DESC.get(stage, STAGE_DESC["loose"])
    if elapsed_days is not None:
        if remaining_days is not None and remaining_days > 0:
            stage_line += f" ({elapsed_days}일째 유지, 다음 단계까지 {remaining_days}일)"
        elif stage == "tight":
            stage_line += f" ({elapsed_days}일째 유지, 최종 단계)"
        else:
            stage_line += f" ({elapsed_days}일째 유지)"

    return f"""[일과후 막걸리 FinOps 비용 최적화 리포트]
- 생성 시각: {timestamp}
- 대상 인프라: AWS EKS 기반 테스트베드
- 적용 정책: {stage_line} 및 OOMKill 제외 완료
* Rightsizing 권장안 요약
- 현재 replicas: {current} → 예측(권장) replicas: {predicted}
- 예측 CPU 사용률: {cpu_usage}%
- 스케일아웃 필요 여부: {"예" if scale_out else "아니오"}
{cost_line}
- 스케일링 상태: {keda_status}
위 권장안을 GitOps(Argo CD) 파이프라인에 최종 승인하여 반영하시겠습니까?
"""


def main():
    forecast = load_forecast()
    stage, elapsed_days, remaining_days = resolve_stage()
    keda_status = get_keda_status()
    report = build_report(forecast, stage, elapsed_days, remaining_days, keda_status)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    print(f"✅ {REPORT_FILE} 생성 완료 (KRR_STAGE={stage}, KEDA={keda_status})")


if __name__ == "__main__":
    main()
