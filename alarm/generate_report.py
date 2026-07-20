#!/usr/bin/env python3
"""
Chronos-2 예측 결과를 읽어서 finops_report.md를 실제 데이터로 생성하는 스크립트
"""
import json
import os

FORECAST_FILE = os.environ.get("FORECAST_FILE", os.path.expanduser("~/k8s-manifest/forecast_result.json"))
REPORT_FILE = os.environ.get("REPORT_FILE", os.path.expanduser("~/practical-project/finops_report.md"))

# KRR 임계값 단계 (초기엔 느슨하게, 점점 타이트하게) - 나중에 자동 승급 로직으로 대체 예정
KRR_STAGE = os.environ.get("KRR_STAGE", "loose")  # loose | medium | tight
STAGE_DESC = {
    "loose":  "CPU 감소 최대 50% 제한 (초기 느슨한 단계)",
    "medium": "CPU 감소 최대 30% 제한 (중간 단계)",
    "tight":  "CPU 감소 최대 10% 제한 (안정화 단계)",
}

def load_forecast():
    with open(FORECAST_FILE) as f:
        return json.load(f)

def build_report(forecast):
    current = forecast["current_replicas"]
    predicted = forecast["predicted_replicas"]
    cpu_usage = forecast["predicted_cpu_usage"]
    scale_out = forecast["scale_out_needed"]
    timestamp = forecast.get("timestamp", "N/A")

    savings_pct = round((1 - predicted / current) * 100, 1) if current > 0 else 0

    return f"""[일과후 막걸리 FinOps 비용 최적화 리포트]

- 생성 시각: {timestamp}
- 대상 인프라: AWS EKS 기반 테스트베드
- 적용 정책: {STAGE_DESC.get(KRR_STAGE, STAGE_DESC['loose'])} 및 OOMKill 제외 완료

* Rightsizing 권장안 요약
- 현재 replicas: {current} → 예측(권장) replicas: {predicted}
- 예측 CPU 사용률: {cpu_usage}%
- 스케일아웃 필요 여부: {"예" if scale_out else "아니오"}
- 예상 비용 절감율: 온디맨드 대비 약 {savings_pct}% 절감 가능
- 스케일링 상태: (KEDA 연동 상태는 alarm 파트와 별도 연동 필요)

위 권장안을 GitOps(Argo CD) 파이프라인에 최종 승인하여 반영하시겠습니까?
"""

def main():
    forecast = load_forecast()
    report = build_report(forecast)
    with open(REPORT_FILE, "w") as f:
        f.write(report)
    print(f"✅ {REPORT_FILE} 생성 완료")

if __name__ == "__main__":
    main()
