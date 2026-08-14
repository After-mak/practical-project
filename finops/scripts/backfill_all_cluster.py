# finops/scripts/backfill_all_cluster.py
import json
import os
import glob
import random
import subprocess
import time

# 1. kubectl로 클러스터 Pod 및 PVC 정보 수집
print("🔍 현재 클러스터의 Pod 및 PVC 정보 조회 중...")
cmd_pods = "kubectl get pods -A -o json"
res_pods = subprocess.check_output(cmd_pods, shell=True)
pods_data = json.loads(res_pods)

cmd_pvcs = "kubectl get pvc -A -o json"
res_pvcs = subprocess.check_output(cmd_pvcs, shell=True)
pvcs_data = json.loads(res_pvcs)

print("🚀 클러스터 5개 항목 전체 [30일치 시계열 연속 데이터] 백필 파일 생성 시작...")

openmetrics_lines = []
now = int(time.time())
days_30_sec = 30 * 86400
start_time = now - days_30_sec

# OpenMetrics 헤더 선언 (표준 메트릭 규격)
openmetrics_lines.extend([
    "# HELP kube_pod_container_resource_requests The number of requested request resource by a container.",
    "# TYPE kube_pod_container_resource_requests gauge",
    "# HELP container_cpu_usage_seconds_total Total seconds of CPU time spent in seconds.",
    "# TYPE container_cpu_usage_seconds_total counter",
    "# HELP container_memory_working_set_bytes Current memory working set in bytes.",
    "# TYPE container_memory_working_set_bytes gauge",
    "# HELP container_fs_usage_bytes Number of bytes consumed on this filesystem.",
    "# TYPE container_fs_usage_bytes gauge",
    "# HELP container_network_receive_bytes_total Cumulative count of bytes received.",
    "# TYPE container_network_receive_bytes_total counter",
    "# HELP kubelet_volume_stats_capacity_bytes Capacity in bytes of the volume.",
    "# TYPE kubelet_volume_stats_capacity_bytes gauge",
    "# HELP kubelet_volume_stats_used_bytes Number of used bytes in the volume.",
    "# TYPE kubelet_volume_stats_used_bytes gauge",
])

# 2. 파드 기준 메트릭 생성
# rate() 연산 및 그래프 스무딩을 위해 15분(900초) 단위로 생성
STEP_SEC = 900 

for item in pods_data.get("items", []):
    namespace = item["metadata"]["namespace"]
    pod_name = item["metadata"]["name"]
    containers = [c["name"] for c in item["spec"].get("containers", [])]

    for container in containers:
        req_cpu = random.choice([0.5, 1.0, 2.0])
        req_mem = random.choice([512, 1024, 2048]) * 1024 * 1024
        req_storage = random.choice([1, 5, 10]) * 1024 * 1024 * 1024

        base_cpu_rate = random.uniform(0.08, 0.25)
        base_mem_usage = random.uniform(150, 450) * 1024 * 1024
        base_storage_usage = random.uniform(200, 600) * 1024 * 1024

        is_idle_pod = random.random() < 0.2
        base_net_rate = 0 if is_idle_pod else random.uniform(5000, 50000)

        cumulative_cpu = random.uniform(50000, 100000)
        cumulative_net = random.uniform(1000000, 5000000)

        for t in range(start_time, now, STEP_SEC):
            hourly_cpu_increase = base_cpu_rate * STEP_SEC * random.uniform(0.85, 1.15)
            cumulative_cpu += hourly_cpu_increase

            hourly_net_increase = base_net_rate * STEP_SEC * random.uniform(0.8, 1.2)
            cumulative_net += hourly_net_increase

            # [1] CPU
            openmetrics_lines.append(
                f'kube_pod_container_resource_requests{{namespace="{namespace}",pod="{pod_name}",container="{container}",resource="cpu"}} {req_cpu} {t}'
            )
            openmetrics_lines.append(
                f'container_cpu_usage_seconds_total{{namespace="{namespace}",pod="{pod_name}",container="{container}"}} {round(cumulative_cpu, 2)} {t}'
            )

            # [2] Memory
            openmetrics_lines.append(
                f'kube_pod_container_resource_requests{{namespace="{namespace}",pod="{pod_name}",container="{container}",resource="memory"}} {req_mem} {t}'
            )
            mem_val = int(base_mem_usage * random.uniform(0.92, 1.08))
            openmetrics_lines.append(
                f'container_memory_working_set_bytes{{namespace="{namespace}",pod="{pod_name}",container="{container}"}} {mem_val} {t}'
            )

            # [3] Storage
            openmetrics_lines.append(
                f'kube_pod_container_resource_requests{{namespace="{namespace}",pod="{pod_name}",container="{container}",resource="ephemeral_storage"}} {req_storage} {t}'
            )
            storage_val = int(base_storage_usage * random.uniform(0.95, 1.05))
            openmetrics_lines.append(
                f'container_fs_usage_bytes{{namespace="{namespace}",pod="{pod_name}",container="{container}"}} {storage_val} {t}'
            )

            # [4] Network
            openmetrics_lines.append(
                f'container_network_receive_bytes_total{{namespace="{namespace}",pod="{pod_name}",container="{container}"}} {int(cumulative_net)} {t}'
            )

# 3. PVC 기준 메트릭 생성
for item in pvcs_data.get("items", []):
    namespace = item["metadata"]["namespace"]
    pvc_name = item["metadata"]["name"]

    capacity_bytes = random.choice([10, 20, 50]) * 1024 * 1024 * 1024
    used_bytes = int(capacity_bytes * random.uniform(0.08, 0.20))

    for t in range(start_time, now, STEP_SEC):
        openmetrics_lines.append(
            f'kubelet_volume_stats_capacity_bytes{{namespace="{namespace}",persistentvolumeclaim="{pvc_name}"}} {capacity_bytes} {t}'
        )
        current_used = int(used_bytes * random.uniform(0.98, 1.02))
        openmetrics_lines.append(
            f'kubelet_volume_stats_used_bytes{{namespace="{namespace}",persistentvolumeclaim="{pvc_name}"}} {current_used} {t}'
        )

openmetrics_lines.append("# EOF")

output_file = "cluster_30days_metrics.openmetrics"
with open(output_file, "w") as f:
    f.write("\n".join(openmetrics_lines) + "\n")

print(f"✅ OpenMetrics 텍스트 파일 생성 완료: {output_file}")

# -------------------------------------------------------------
# 4. [핵심 추가] promtool 변환 및 Thanos External Labels 주입 로직
# -------------------------------------------------------------
block_out_dir = "./thanos_blocks"
os.makedirs(block_out_dir, exist_ok=True)

print("⚙️ promtool을 실행하여 TSDB 블록 생성 중...")
subprocess.run(
    f"promtool tsdb create-blocks-from openmetrics {output_file} {block_out_dir}",
    shell=True,
    check=True
)

print("🏷️ 생성된 TSDB 블록 meta.json에 Thanos External Labels 주입 중...")
meta_files = glob.glob(f"{block_out_dir}/**/meta.json", recursive=True)

for meta_path in meta_files:
    with open(meta_path, "r") as f:
        meta_data = json.load(f)
    
    # Thanos External Labels 및 메타데이터 주입
    meta_data["thanos"] = {
        "labels": {
            "prometheus": "prometheus/prometheus-stack-kube-prom-prometheus",
            "prometheus_replica": "prometheus-prometheus-stack-kube-prom-prometheus-0"
        },
        "downsample": {
            "resolution": 0
        },
        "source": "sidecar",
        "segment_files": meta_data.get("thanos", {}).get("segment_files", [])
    }
    
    with open(meta_path, "w") as f:
        json.dump(meta_data, f, indent=4)

print(f"🎉 총 {len(meta_files)}개 블록에 Thanos External Labels 주입 완료!")