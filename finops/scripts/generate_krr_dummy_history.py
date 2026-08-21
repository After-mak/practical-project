#!/usr/bin/env python3
"""
KRR이 실제로 쓰는 Prometheus 메트릭(container_cpu_usage_seconds_total,
container_memory_working_set_bytes)을 과거 타임스탬프로 채운 OpenMetrics
파일을 생성합니다. `promtool tsdb create-blocks-from openmetrics`로 이 파일을
Prometheus TSDB에 즉시 백필하면, 실사용 이력이 없는 새 클러스터에서도
KRR이 바로 의미 있는 추천값을 낼 수 있습니다 (시연/데모용).

KRR simple 전략 기본값(history_duration=336h, points_required=100)을 만족하되,
Prometheus 로컬 retention(2d, infra/terraform/.../prometheus/my-values.yaml.tpl 기준)을
넘는 과거 데이터는 클러스터에 반영되자마자 삭제되므로 기본 2일만 생성합니다.
(336h=14일치 lookback은 Thanos Query가 S3 장기 이력으로 채웁니다.)
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

# 시연용으로 준비해둔 시나리오. deployment는 실제 배포된 Deployment 이름과, containers의
# 키는 그 파드 안에 실제로 떠 있는 컨테이너 이름과 반드시 일치해야 KRR이 스캔한
# pod/container 목록(regex)에 걸립니다. Bank of Anthos 백엔드 서비스들(userservice/
# contacts/balancereader/ledgerwriter/transactionhistory)은 파드 하나에 서비스 본체
# 컨테이너 + redis-queue worker 사이드카 컨테이너가 함께 떠 있으므로(mak-app 차트
# templates/2-microservices.yaml 참고), 한 시나리오 안에 컨테이너를 여러 개 정의합니다.
SCENARIOS = {
    "sample-fastapi": {
        "containers": {
            "fastapi": {
                "cpu_avg_cores": 0.012,   # 현재 request 100m 대비 실사용 평균 ~12m -> 과다 프로비저닝 시나리오
                "cpu_jitter": 0.5,
                "mem_avg_mib": 42,        # 현재 request 128Mi 대비 실사용 평균 ~42Mi
                "mem_jitter_mib": 6,
            },
        },
    },
    "sample-worker": {
        "containers": {
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.08,   # 현재 request 361m 대비 평상시 ~80m
                "chronos_spike_cores": 1.2,        # 20분 주기 급증 구간 피크 ~1.2 core
                "mem_avg_mib": 118,        # 현재 request 128Mi 대비 실사용 평균 ~118Mi
                "mem_jitter_mib": 5,
            },
        },
    },
    # --- Bank of Anthos 프론트엔드 (namespace=frontend, mak-app 차트) ---
    # Argo Rollout 리소스라 KRR/finops-apply.yaml이 인식하는 workload 이름은 "frontend"가
    # 아니라 Rollout의 실제 metadata.name인 "mak-app-rollout"입니다 (templates/3-frontend-rollout.yaml
    # 실측 확인, finops-apply.yaml의 케이스 매핑도 동일하게 "frontend/mak-app-rollout/mak-container"
    # 사용). 컨테이너 이름도 "frontend"가 아니라 "mak-container"입니다. 사이드카 없이 단일
    # 컨테이너이고, 사용자 트래픽을 직접 받는 서비스라 worker류의 주기적 스파이크보다는
    # 하루 주기(diurnal) 패턴이 더 그럴듯합니다.
    "mak-app-rollout": {
        "containers": {
            "mak-container": {
                "cpu_avg_cores": 0.035, "cpu_jitter": 0.45,   # 현재 request 200m 대비 실사용 평균 ~17.5%
                "mem_avg_mib": 110, "mem_jitter_mib": 14,      # 현재 request 256Mi 대비 실사용 평균 ~43%
            },
        },
    },
    # --- Bank of Anthos 백엔드 (namespace=backend, mak-app 차트) ---
    # app 컨테이너: request 200m/256Mi 대비 실사용을 낮게 잡아 KRR 라이트사이징 스토리를 만들고,
    # worker 사이드카: request 250m/256Mi 대비 20분 주기 스파이크로 Chronos 예측 대상 변화를 보여줍니다.
    "userservice": {
        "containers": {
            "userservice": {
                "cpu_avg_cores": 0.028, "cpu_jitter": 0.4,
                "mem_avg_mib": 95, "mem_jitter_mib": 12,
            },
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.02, "chronos_spike_cores": 0.20,
                "mem_avg_mib": 55, "mem_jitter_mib": 8,
            },
        },
    },
    "contacts": {
        "containers": {
            "contacts": {
                "cpu_avg_cores": 0.015, "cpu_jitter": 0.5,
                "mem_avg_mib": 68, "mem_jitter_mib": 8,
            },
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.015, "chronos_spike_cores": 0.15,
                "mem_avg_mib": 50, "mem_jitter_mib": 6,
            },
        },
    },
    "balancereader": {
        "containers": {
            # Java/Spring 서비스라 JVM 힙 기본 점유가 상대적으로 높습니다.
            "balancereader": {
                "cpu_avg_cores": 0.05, "cpu_jitter": 0.35,
                "mem_avg_mib": 150, "mem_jitter_mib": 15,
            },
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.025, "chronos_spike_cores": 0.28,
                "mem_avg_mib": 60, "mem_jitter_mib": 8,
            },
        },
    },
    "ledgerwriter": {
        "containers": {
            "ledgerwriter": {
                "cpu_avg_cores": 0.045, "cpu_jitter": 0.4,
                "mem_avg_mib": 140, "mem_jitter_mib": 14,
            },
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.03, "chronos_spike_cores": 0.30,
                "mem_avg_mib": 58, "mem_jitter_mib": 8,
            },
        },
    },
    "transactionhistory": {
        "containers": {
            "transactionhistory": {
                "cpu_avg_cores": 0.06, "cpu_jitter": 0.3,
                "mem_avg_mib": 165, "mem_jitter_mib": 16,
            },
            "worker": {
                "profile": "chronos-periodic-spike",
                "chronos_baseline_cores": 0.028, "chronos_spike_cores": 0.26,
                "mem_avg_mib": 62, "mem_jitter_mib": 9,
            },
        },
    },
}


def chronos_periodic_cpu(timestamp: int, rng: random.Random, baseline_cores: float = 0.08, spike_cores: float = 1.2) -> float:
    """20분 주기의 정상->상승->급증->회복 CPU 패턴을 만듭니다."""

    minute = (timestamp % 1200) / 60
    if minute < 8:
        base = baseline_cores
    elif minute < 12:
        base = baseline_cores + ((minute - 8) / 4) * (spike_cores - baseline_cores)
    elif minute < 16:
        base = spike_cores
    else:
        base = (spike_cores * 0.33) - ((minute - 16) / 4) * (spike_cores * 0.33 - baseline_cores)
    return max(0.01 * baseline_cores / 0.08, base * rng.uniform(0.95, 1.05))


def generate_series(
    container_cfg: dict,
    namespace: str,
    pod: str,
    container: str,
    days: int,
    seed: int,
):
    """(cpu_lines, mem_lines) 튜플을 리턴합니다. CPU는 누적 카운터, 메모리는 게이지입니다."""
    rng = random.Random(seed)
    profile = container_cfg.get("profile", "krr-rightsizing")
    labels_common = f'namespace="{namespace}",pod="{pod}",container="{container}",job="kubelet"'

    now = int(time.time())
    start = now - days * 86400
    timestamps = list(range(start, now + 1, STEP_SECONDS))

    cpu_lines = []
    mem_lines = []
    cumulative_cpu_seconds = 0.0

    for ts in timestamps:
        if profile == "chronos-periodic-spike":
            instantaneous_cpu = chronos_periodic_cpu(
                ts, rng,
                container_cfg.get("chronos_baseline_cores", 0.08),
                container_cfg.get("chronos_spike_cores", 1.2),
            )
        else:
            # 하루 주기(diurnal) 패턴 + 랜덤 노이즈로 그럴듯한 변동을 만듭니다.
            hour_of_day = (ts % 86400) / 3600.0
            diurnal = 0.85 + 0.3 * math.sin((hour_of_day - 9) / 24.0 * 2 * math.pi)
            noise = rng.uniform(1 - container_cfg["cpu_jitter"], 1 + container_cfg["cpu_jitter"])
            instantaneous_cpu = max(
                0.0005, container_cfg["cpu_avg_cores"] * diurnal * noise
            )
        cumulative_cpu_seconds += instantaneous_cpu * STEP_SECONDS
        cpu_lines.append(
            f"container_cpu_usage_seconds_total{{{labels_common}}} {cumulative_cpu_seconds:.6f} {ts}"
        )

        mem_noise = rng.uniform(-container_cfg["mem_jitter_mib"], container_cfg["mem_jitter_mib"])
        mem_mib = max(8.0, container_cfg["mem_avg_mib"] + mem_noise)
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
    parser.add_argument("--namespace", required=True, help="예: sample-fastapi, backend")
    parser.add_argument("--deployment", required=True, choices=sorted(SCENARIOS.keys()), help="시나리오가 정의된 deployment 이름")
    parser.add_argument("--pod", required=True, help="현재 실제로 떠있는 pod 이름 (kubectl get pods로 확인)")
    parser.add_argument("--days", type=int, default=2, help="생성할 과거 일수 (기본 2일, Prometheus 로컬 retention과 일치)")
    parser.add_argument("--seed", type=int, default=42, help="재현 가능한 랜덤 시드 (시연 때마다 같은 값이 나오도록)")
    parser.add_argument("--output", required=True, help="생성된 OpenMetrics 파일 경로")
    args = parser.parse_args()

    scenario = SCENARIOS[args.deployment]
    all_cpu_lines = []
    all_mem_lines = []
    for container_name, container_cfg in scenario["containers"].items():
        # 컨테이너마다 다른 시드를 줘서(같은 파드 안 app/worker가 완전히 같은 패턴으로
        # 겹치지 않도록) 재현성은 유지하면서 컨테이너별로 다른 변동을 만듭니다.
        container_seed = args.seed + (abs(hash(container_name)) % 1000)
        cpu_lines, mem_lines = generate_series(
            container_cfg, args.namespace, args.pod, container_name, args.days, container_seed,
        )
        all_cpu_lines.extend(cpu_lines)
        all_mem_lines.extend(mem_lines)

    write_openmetrics(args.output, all_cpu_lines, all_mem_lines)
    print(f"[generate_krr_dummy_history] {args.output} 생성 완료 "
          f"({len(scenario['containers'])}개 컨테이너, {len(all_cpu_lines)} CPU 샘플, "
          f"{len(all_mem_lines)} 메모리 샘플, {args.days}일치)")


if __name__ == "__main__":
    main()
