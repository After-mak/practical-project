# Bank of Anthos 라이브 트래픽 사전검증 결과 (2026-08-24)

## 한눈에 보는 결론

- 부하 생성기, 결과 영구 저장, Prometheus 수집, KEDA/HPA 확장, readiness 처리는 동작한다.
- 3분 압축 검증은 최종 설정에서 2,674/2,674 성공했다.
- 30분 지속 검증은 40 RPS 스파이크에서 299건의 타임아웃과 68건의 dropped iteration이 발생해 실패했다.
- 따라서 장기 PRE/KRR/POST 실행을 시작할 준비는 아직 완료되지 않았다.
- 오늘은 추가 테스트를 중단한다. 다음 작업은 스파이크 선행 확장 개선 후 30분 검증 재실행이다.

## 검증 범위와 조건

- 시나리오: 저부하 5분 → 정상 10분 → 피크 5분 → 스파이크 5분 → 회복 5분
- RPS: 1 → 10 → 25 → 40 → 3
- 인증: shared 모드. setup에서 한 번 로그인하고 VU가 인증 쿠키를 공유한다.
- 요청 제한시간: 10초
- 프론트엔드: min 2, max 10
- 최종 CPU scaler: 파드당 0.10 core
- 최종 네트워크 scaler: sum(irate(container_network_transmit_bytes_total[1m])), 파드당 150,000 bytes/s
- 프론트엔드 readiness/startup: TCP 8080
- 테스트 데이터 변경 요청: 비활성화(paymentPercent=0)

## 오늘 반영한 주요 수정

1. 실제 HTTP 부하에 반응하는 프론트엔드/백엔드 CPU scaler를 추가했다.
2. 프론트엔드 minReplica를 2로 올리고 maxReplica를 10으로 제한했다.
3. k6 요청 제한시간을 10초로 고정해 VU 폭증을 제한했다.
4. per-VU 로그인 폭증을 제거하고 shared 인증을 기본값으로 만들었다.
5. k6 summary가 종료 시 깨지는 문제를 수정했다.
6. 프론트엔드 TCP readiness/startup probe를 추가해 준비되지 않은 Pod가 Service endpoint에 들어가지 않게 했다.
7. I/O 포화에 대응하도록 네트워크 기반 scaler를 추가했다.
8. 희소 표본에서 0이 되는 30초 rate 대신 1분 범위 irate를 사용했다.
9. 테스트 Job은 완료 후 Git 설정에서 비활성화했다.

## 주요 테스트 결과

| 실행 ID | 시간 | 결과 | 성공률 | HTTP 오류 | Dropped | E2E p95 | E2E p99 |
|---|---:|---|---:|---:|---:|---:|---:|
| boa-smoke-ready-20260824-065540 | 3분 | 통과 | 100% | 0 | 0 | 25.8 ms | 44.0 ms |
| boa-smoke-network-20260824-0800 | 3분 | 통과 | 100% | 0 | 0 | 30.0 ms | 116.3 ms |
| boa-smoke-30m-network-20260824-1710 | 30분 | 실패 | 99.899% | 27 | 27 | 30.0 ms | 4,874.9 ms |
| boa-smoke-irate-20260824-1800 | 3분 | 통과 | 100% | 0 | 0 | 26.0 ms | 40.6 ms |
| boa-smoke-30m-irate-20260824-1811 | 30분 | 실패 | 98.878% | 299 | 68 | 4,012.0 ms | 9,999.8 ms |

중간에 중단한 실행:

- boa-smoke-30m-20260824-070142: CPU 100m scaler가 I/O 포화를 늦게 감지해 스파이크에서 실패했다.
- boa-smoke-30m-v2-20260824-072912: CPU 50m scaler가 시작 CPU를 부하로 오인해 10개까지 연쇄 확장되어 중단했다.
- boa-smoke-30m-final-20260824-1751: 30초 rate 표본이 간헐적으로 0이 되어 정상 구간에서 조기 중단했다.

## 최종 30분 실행 상세

- 실행 ID: boa-smoke-30m-irate-20260824-1811
- 완료 흐름: 26,637
- 성공: 26,338
- 실패: 299
- HTTP 오류율: 1.1225%
- Dropped iterations: 68
- 평균 처리량: 14.795 iterations/s
- E2E latency: 평균 439.8 ms, p95 4,012.0 ms, p99 9,999.8 ms, max 10,007 ms
- k6 VU: max 166
- 프론트엔드 replica: 평균 4.87, max 10
- 프론트엔드 CPU 사용량(전체): 평균 0.187 core, p95 0.473 core, max 0.547 core
- 프론트엔드 Memory working set(전체): 평균 443.5 MiB, p95 994.4 MiB, max 1,004.3 MiB
- 프론트엔드 CPU throttling: 평균 5.51%, p95 12.31%, max 13.80%
- 프론트엔드/백엔드 Pod restart 증가: 0
- 관찰된 OOMKilled: 0
- worker node 수: 평균/최대 8

실패 299건과 dropped 68건은 모두 spike 구간이었다.

- 최초 타임아웃: 2026-08-24 18:32:59 KST
- 마지막 타임아웃: 2026-08-24 18:37:33 KST
- 피크에서는 프론트엔드가 2 → 3 → 5개로 확장됐다.
- 스파이크에서는 5 → 7개로 확장했지만 타임아웃이 계속됐다.
- 스파이크 후반에 7 → 10개가 된 뒤 파드당 네트워크가 약 97 KB/s로 내려왔다.
- 결론: 최대 용량은 확보됐지만 7 → 10 확장이 너무 늦었다. 짧은 압축 테스트만으로는 이 지속 포화를 발견할 수 없었다.

## 공식 성공 기준과 판정

k6/bank-krr-success-criteria.json 기준:

| 기준 | 제한 | 최종 값 | 판정 |
|---|---:|---:|---|
| System error rate | < 1% | 1.1225% | 실패 |
| Business failure rate | < 1% | 1.1225% | 실패 |
| Dropped iterations | 0 | 68 | 실패 |
| CPU throttling 평균 | < 5% | 5.51% | 실패 |
| CPU throttling p95 | < 20% | 12.31% | 통과 |
| OOM 증가 | 0 | 0 | 통과 |
| Restart 증가 | 0 | 0 | 통과 |

PRE/POST 비교용 p95/p99 regression과 resource reduction 기준은 PRE와 POST가 모두 있어야 판정할 수 있다.

## 결과물 위치

로컬 결과 디렉터리(보안 및 용량 때문에 Git 제외):

- k6/results/boa-smoke-30m-irate-20260824-1811/summary.json
- k6/results/boa-smoke-30m-irate-20260824-1811/k6-summary.json
- k6/results/boa-smoke-30m-irate-20260824-1811/collected.json
- k6/results/boa-smoke-30m-irate-20260824-1811/collected.csv
- k6/results/boa-smoke-30m-irate-20260824-1811/equivalence.json

클러스터 원본:

- PVC: frontend/bank-loadgen-results
- summary-boa-smoke-30m-irate-20260824-181.json
- k6-summary-boa-smoke-30m-irate-20260824-181.json
- raw-boa-smoke-30m-irate-20260824-181.json

관련 최종 커밋:

- practical-project dev: 8cd0fac (shared 인증), fc2e764 (요청 제한시간)
- mak-argocd-deploy main: 00efbf4 (TCP readiness), f3c686a (네트워크 scaler), 1c81697 (선행 확장 기준), ae56b59 (irate), 50930ad (최종 Job 비활성화)

## 다음 작업

오늘은 여기서 테스트를 종료한다.

다음 작업일 권장 순서:

1. 네트워크 목표를 약 100 KB/s로 낮추거나 피크 단계에서 7개 이상을 미리 확보해 스파이크 시작 전에 10개에 도달하도록 수정한다.
2. 응답 전송량은 포화 시 오히려 감소할 수 있으므로, 가능하면 요청 수·동시 요청·대기시간 기반 지표를 추가한다.
3. 동일 30분 시나리오를 다시 실행해 error 0, dropped 0, restart 0, OOM 0을 확인한다.
4. 통과 후 PRE 3시간(cycles=6)을 실행한다.
5. KRR 권장값을 산출·적용하고 상태를 확인한다.
6. 동일 조건 POST 3시간(cycles=6)을 실행한다.
7. compare_bank_krr_runs.py로 전후 JSON/CSV/Markdown 비교 보고서를 생성한다.

PRE와 POST는 RPS, cycles, 인증 방식, DB 상태, 이미지, 노드풀 조건을 동일하게 유지해야 한다.

