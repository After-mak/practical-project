import requests
import torch
import json
import math
import os
import subprocess
from datetime import datetime, timedelta, timezone
from chronos import ChronosPipeline

PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")
TARGET_DEPLOYMENT = os.environ.get("CHRONOS_TARGET_DEPLOYMENT", "test-overprovisioned")
TARGET_NAMESPACE = os.environ.get("CHRONOS_TARGET_NAMESPACE", "default")
POD_PATTERN = os.environ.get("CHRONOS_POD_PATTERN", TARGET_DEPLOYMENT + ".*")
THRESHOLD = float(os.environ.get("CHRONOS_THRESHOLD", "0.3"))
CAPACITY_PER_REPLICA = float(os.environ.get("CHRONOS_CAPACITY_PER_REPLICA", "0.5"))
LOOKBACK_HOURS = float(os.environ.get("CHRONOS_LOOKBACK_HOURS", "2"))
FORECAST_OUTPUT = os.environ.get("FORECAST_FILE", os.path.expanduser("~/k8s-manifest/forecast_result.json"))

QUERY = 'sum(rate(container_cpu_usage_seconds_total{pod=~"' + POD_PATTERN + '"}[5m])) by (pod)'


def get_current_replicas():
    try:
        result = subprocess.run(
            ["kubectl", "get", "deployment", TARGET_DEPLOYMENT, "-n", TARGET_NAMESPACE,
             "-o", "jsonpath={.spec.replicas}"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return int(result.stdout.strip())
    except Exception as e:
        print(f"현재 replica 수 조회 실패, 기본값 1 사용: {e}")
        return 1


end = datetime.now(timezone.utc)
start = end - timedelta(hours=LOOKBACK_HOURS)
resp = requests.get(f"{PROM_URL}/api/v1/query_range", params={
    "query": QUERY,
    "start": start.isoformat(),
    "end": end.isoformat(),
    "step": "60s",
})
resp.raise_for_status()
data = resp.json()
results = data["data"]["result"]
if not results:
    raise SystemExit(
        f"Prometheus에서 '{POD_PATTERN}' 패턴의 데이터를 못 가져왔습니다. "
        f"대상 파드가 떠 있는지, 포트포워딩(9090)이 되어있는지, "
        f"CHRONOS_LOOKBACK_HOURS가 파드 기동 시점보다 긴지 확인하세요."
    )

values = [float(v[1]) for v in results[0]["values"]]
print(f"가져온 데이터 포인트 수: {len(values)}")
print("최근 10개 값:", values[-10:])

context = torch.tensor(values, dtype=torch.float32)
print("모델 불러오는 중...")
pipeline = ChronosPipeline.from_pretrained(
    "amazon/chronos-t5-small",
    device_map="cpu",
    torch_dtype=torch.float32,
)
prediction_length = 12  # step=60s 기준 향후 12분 예측
forecast = pipeline.predict(context, prediction_length)
median_forecast = forecast[0].median(dim=0).values
print("향후 12분 CPU 사용량 예측(중간값):")
print(median_forecast)

if median_forecast.max().item() > THRESHOLD:
    print(f"예측치가 임계값({THRESHOLD})을 초과 → 스케일아웃 신호")
else:
    print(f"예측치가 임계값({THRESHOLD}) 이내 → 스케일아웃 불필요")

predicted_max = median_forecast.max().item()
current_replicas = get_current_replicas()
scale_out_needed = predicted_max > THRESHOLD
predicted_replicas = (
    max(1, math.ceil(predicted_max / CAPACITY_PER_REPLICA))
    if scale_out_needed else current_replicas
)

result = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "pod": TARGET_DEPLOYMENT,
    "predicted_cpu_usage": round(predicted_max, 6),
    "scale_out_needed": scale_out_needed,
    "current_replicas": current_replicas,
    "predicted_replicas": predicted_replicas,
}
os.makedirs(os.path.dirname(FORECAST_OUTPUT), exist_ok=True)
with open(FORECAST_OUTPUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\n=== KEDA 연동용 예측 결과 ({FORECAST_OUTPUT}에 저장됨) ===")
print(json.dumps(result, ensure_ascii=False, indent=2))
