# Bank of Anthos KRR PRE/POST 최종 보고서

- 작성 시각(UTC):
- PRE Run ID:
- POST Run ID:
- Application commit:
- PRE/POST GitOps commit:
- Application image digest:
- Load generator image digest:
- Scenario와 SHA-256:
- DB snapshot/seed ID:
- KRR history duration:
- Prometheus/Thanos URL:
- 실험 한계:

## 최종 판정

**PENDING**

| 검증 항목 | 기준 | 결과 | 판정 |
|---|---:|---:|---|
| OOMKilled 증가 | 0 | | |
| 리소스 부족 restart | 0 | | |
| 시스템 error rate | <1% | | |
| p95 악화 | ≤10% | | |
| p99 악화 | ≤15% | | |
| 성공 throughput | PRE의 ≥95% | | |
| 평균 CPU throttling | <5% | | |
| p95 CPU throttling | <20% | | |
| CPU 또는 Memory request | 절감 | | |

## PRE/POST 동등성

애플리케이션 이미지, load generator 이미지·script hash, offered RPS, 실행시간, DB 초기 상태, autoscaling, NodePool을 비교한다. mismatch가 하나라도 있으면 결과를 FAIL 또는 재실험으로 판정한다.

## 컨테이너별 결과

`compare_bank_krr_runs.py`가 생성한 표를 삽입한다.

## 비용

- Request 기반 할당비용(추정):
- 실제 Worker Node 비용:
- 고정 인프라 비용:
- 주의: Request 비용 추정치는 AWS 청구액이 아니다.

## KRR 적용값

| 식별자 | Current Request | KRR | Final/Applied | Limit 변경 여부 |
|---|---|---|---|---|
| frontend/mak-app-rollout/mak-container | | | | 변경 없음 |
| backend/userservice/userservice | | | | 변경 없음 |
| backend/userservice/worker | | | | 변경 없음 |
| backend/contacts/contacts | | | | 변경 없음 |
| backend/contacts/worker | | | | 변경 없음 |
| backend/balancereader/balancereader | | | | 변경 없음 |
| backend/balancereader/worker | | | | 변경 없음 |
| backend/ledgerwriter/ledgerwriter | | | | 변경 없음 |
| backend/ledgerwriter/worker | | | | 변경 없음 |
| backend/transactionhistory/transactionhistory | | | | 변경 없음 |
| backend/transactionhistory/worker | | | | 변경 없음 |

## Blocker와 후속 작업

- frontend Rollout KRR 발견 상태:
- Thanos 2일 이전 query 상태:
- S3 block/Store Gateway 상태:
- 서비스별 HTTP 계측 추가:
- Queue producer/Hybrid autoscaling: 이번 결과에서 제외
