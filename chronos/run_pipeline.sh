#!/bin/bash
# Chronos-2 예측 + FinOps 리포트 생성 파이프라인 (주기 실행용)
LOG=~/practical-project/chronos/pipeline.log
echo "=== $(date -u +%FT%TZ) 파이프라인 시작 ===" >> "$LOG"

# 기존에 떠있을 수 있는 포트포워드 정리
pkill -f "port-forward.*9090" 2>/dev/null
sleep 1

kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring >> "$LOG" 2>&1 &
PF_PID=$!
sleep 5

source ~/chronos-env/bin/activate
cd ~/practical-project

python3 chronos/chronos_prometheus.py >> "$LOG" 2>&1
python3 alarm/generate_report.py >> "$LOG" 2>&1

deactivate
kill "$PF_PID" 2>/dev/null

echo "=== $(date -u +%FT%TZ) 파이프라인 종료 ===" >> "$LOG"
