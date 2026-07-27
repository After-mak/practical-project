#!/usr/bin/env python3
"""
KRR이 실제로 쓰는 Prometheus 메트릭(container_cpu_usage_seconds_total,
container_memory_working_set_bytes)을 과거 타임스탬프로 채운 OpenMetrics
파일을 생성합니다. `promtool tsdb create-blocks-from openmetrics`로 이 파일을
Prometheus TSDB에 즉시 백필하면, 실사용 이력이 없는 새 클러스터에서도
KRR이 바로 의미 있는 추천값을 낼 수 있습니다 (시연/데모용).

KRR simple 전략 기본값(history_duration=336h, points_required=100)을 만족하되,
Prometheus retention(7d, infra/terraform/.../prometheus/my-values.yaml.tpl 기준)을
넘는 과거 데이터는 클러스터에 반영되자마자 삭제되므로 기본 7일만 생성합니다.
"""
import argparse
import math
import random
import time


# KRR simple 전략의 기본 timeframe_duration(=step)이 1.25분이고, 내부적으로
# rate(...[step])로 순간 사용률을 계산합니다. 원본 샘플 간격이 이 step보다 넓으면
# 그 구간에 샘플이 1개 이하만 걸려서 rate()가 값을 아예 못 냅니다(직접 promtool로
# 백필해서 재현 확인함). 그래서 실제 Prometheus scrape_interval과 비슷한 30초로 촘촘하게 채웁니다.
STEP_SECONDS = 30

# 시연용으로 준비해둔 시나리오. container/pod은 실제 배포된 이름과 반드시 일치해야
# KRR이 스캔한 pod 목록(regex)에 걸립니다.
SCENARIOS = {
    "sample-fastapi": {
        "container": "fastapi",
        "cpu_avg_cores": 0.012,   # 현재 request 100m 대비 실사용 평균 ~12m -> 과다 프로비저닝 시나리오
        "cpu_jitter": 0.5,
        "mem_avg_mib": 42,        # 현재 request 128Mi 대비 실사용 평균 ~42Mi
        "mem_jitter_mib": 6,
    },
    "sample-worker": {
        "container": "worker",
        "cpu_avg_cores": 0.07,    # 현재 request 100m 대비 실사용 평균 ~70m -> 이미 잘 맞춰진 시나리오
        "cpu_jitter": 0.15,
        "mem_avg_mib": 118,       # 현재 request 128Mi 대비 실사용 평균 ~118Mi
        "mem_jitter_mib": 5,
    },
}


def generate_series(scenario: dict, namespace: str, pod: str, days: int, seed: int):
    """(cpu_lines, mem_lines) 튜플을 리턴합니다. CPU는 누적 카운터, 메모리는 게이지입니다."""
    rng = random.Random(seed)
    container = scenario["container"]
    labels_common = f'namespace="{namespace}",pod="{pod}",container="{container}",job="kubelet"'

    now = int(time.time())
    start = now - days * 86400
    timestamps = list(range(start, now + 1, STEP_SECONDS))

    cpu_lines = []
    mem_lines = []
    cumulative_cpu_seconds = 0.0

    for i, ts in enumerate(timestamps):
        # 하루 주기(diurnal) 패턴 + 랜덤 노이즈로 그럴듯한 변동을 만듭니다.
        hour_of_day = (ts % 86400) / 3600.0
        diurnal = 0.85 + 0.3 * math.sin((hour_of_day - 9) / 24.0 * 2 * math.pi)
        noise = rng.uniform(1 - scenario["cpu_jitter"], 1 + scenario["cpu_jitter"])
        instantaneous_cpu = max(0.0005, scenario["cpu_avg_cores"] * diurnal * noise)
        cumulative_cpu_seconds += instantaneous_cpu * STEP_SECONDS
        cpu_lines.append(
            f"container_cpu_usage_seconds_total{{{labels_common}}} {cumulative_cpu_seconds:.6f} {ts}"
        )

        mem_noise = rng.uniform(-scenario["mem_jitter_mib"], scenario["mem_jitter_mib"])
        mem_mib = max(8.0, scenario["mem_avg_mib"] + mem_noise)
        mem_bytes = int(mem_mib * 1024 * 1024)
        mem_lines.append(
            f"container_memory_working_set_bytes{{{labels_common}}} {mem_bytes} {ts}"
        )

    return cpu_lines, mem_lines


def write_openmetrics(path: str, cpu_lines: list, mem_lines: list):
    with open(path, "w") as f:
        f.write("# HELP container_cpu_usage_seconds_total Cumulative cpu time consumed by the container in core-seconds.\n")
        f.write("# TYPE container_cpu_usage_seconds_total counter\n")
        f.write("\n".join(cpu_lines) + "\n")
        f.write("# HELP container_memory_working_set_bytes Current working set memory usage in bytes.\n")
        f.write("# TYPE container_memory_working_set_bytes gauge\n")
        f.write("\n".join(mem_lines) + "\n")
        f.write("# EOF\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True, help="예: sample-fastapi")
    parser.add_argument("--deployment", required=True, choices=sorted(SCENARIOS.keys()), help="시나리오가 정의된 deployment 이름")
    parser.add_argument("--pod", required=True, help="현재 실제로 떠있는 pod 이름 (kubectl get pods로 확인)")
    parser.add_argument("--days", type=int, default=7, help="생성할 과거 일수 (기본 7일, Prometheus retention과 일치)")
    parser.add_argument("--seed", type=int, default=42, help="재현 가능한 랜덤 시드 (시연 때마다 같은 값이 나오도록)")
    parser.add_argument("--output", required=True, help="생성된 OpenMetrics 파일 경로")
    args = parser.parse_args()

    scenario = SCENARIOS[args.deployment]
    cpu_lines, mem_lines = generate_series(scenario, args.namespace, args.pod, args.days, args.seed)
    write_openmetrics(args.output, cpu_lines, mem_lines)
    print(f"[generate_krr_dummy_history] {args.output} 생성 완료 "
          f"({len(cpu_lines)} CPU 샘플, {len(mem_lines)} 메모리 샘플, {args.days}일치)")


if __name__ == "__main__":
    main()
