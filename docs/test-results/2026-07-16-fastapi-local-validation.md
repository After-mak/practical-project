# 2026-07-16 FastAPI 사전 작업 로컬 테스트 결과

## 1. 이번 단계 범위

- 브랜치: `feature/sample-fastapi`
- 기준 커밋: `70f1d1a`
- 테스트 일시: 2026-07-16 16:55~17:01 KST
- 검증 환경: Windows 로컬 PC의 Docker Compose 환경

이번 결과는 ElastiCache Terraform, ECR, Kubernetes 작업 전 단계만 대상으로 합니다.

### 완료 체크리스트

- [x] Redis 설정을 환경변수로 관리
- [x] TLS 옵션 구현
- [x] FastAPI와 Worker Redis Client 공통화
- [x] 연결 Timeout 설정
- [x] Redis 장애 처리 확인
- [x] `.env.example` 수정
- [x] 단위 테스트 통과
- [x] Docker Compose 회귀 테스트 통과

다음 단계인 ElastiCache Terraform, ECR, Kubernetes 관련 파일은 이번 변경에 포함하지 않았습니다.

## 2. 변경 내용

### Redis 환경변수

다음 설정을 `Settings`와 `.env.example`에서 관리하도록 구성했습니다.

```text
REDIS_URL
REDIS_HOST
REDIS_PORT
REDIS_DB
REDIS_PASSWORD
REDIS_SSL
REDIS_SSL_CERT_REQS
REDIS_CONNECT_TIMEOUT
REDIS_SOCKET_TIMEOUT
REDIS_HEALTH_CHECK_INTERVAL
REDIS_RETRY_ATTEMPTS
REDIS_QUEUE_KEY
```

- `REDIS_URL`이 있으면 URL을 우선 사용합니다.
- `redis://`는 일반 연결, `rediss://`는 TLS 연결로 처리합니다.
- Host 방식에서는 `REDIS_SSL=true`로 TLS를 켭니다.
- 인증서 검증 기본값은 `required`입니다.
- Password가 비어 있으면 인증 없이 연결합니다.
- Queue Key는 기존 `REDIS_QUEUE_KEY`와 지시서의 `QUEUE_KEY`를 모두 지원합니다.

### 공통 Redis Client

FastAPI와 Worker는 기존처럼 같은 `create_redis_client()`를 사용합니다. 공통 Client에 아래 옵션을 적용했습니다.

- Connect Timeout
- Socket Timeout
- Health Check Interval
- Exponential Backoff Retry
- Connection/Timeout 오류 재시도
- UTF-8 문자열 응답을 위한 `decode_responses=True`

Redis 오류 응답은 접속 주소나 Password를 포함하지 않고 아래처럼 반환합니다.

```json
{"detail":"Redis unavailable"}
```

## 3. 실행 환경

| 도구 | 버전 |
| --- | --- |
| Python | 3.11.7 |
| pytest | 8.3.4 |
| Docker Engine | 29.6.1 |
| Docker Compose | v5.2.0 |
| k6 | v2.0.0 |

Python 테스트는 개발 의존성이 설치된 `apps/sample-fastapi/.venv`에서 실행했습니다.

## 4. 단위 테스트

실행 명령:

```powershell
apps/sample-fastapi/.venv/Scripts/python.exe -m pytest `
  apps/sample-fastapi/tests `
  --junitxml=docs/test-results/pytest.xml -v
```

결과:

```text
13 passed in 0.45s
```

검증한 내용:

- 기존 FastAPI API, QueueService, Worker 회귀 테스트
- 로컬 Redis 기본 연결은 TLS를 사용하지 않음
- `REDIS_SSL=true`에서 TLS와 인증서 검증 적용
- `rediss://` URL이 Host 방식 SSL Flag보다 우선함
- 잘못된 Scheme, 인증서 옵션, Timeout, Retry 값은 연결 전에 차단
- Redis 오류 시 HTTP 503 반환
- Queue를 여러 Service가 공유하고 Worker가 작업을 한 번씩 처리함

원본 JUnit 결과: [pytest.xml](./pytest.xml)

## 5. Docker Compose 회귀 테스트

실행 명령:

```powershell
docker compose --profile worker up -d --build --scale queue-worker=2
docker compose --profile worker ps
```

빌드 이미지:

```text
sample-fastapi:v0.4.0-local
sha256:2e6b4f237ba1e59f6db927519eae9a6ce5880f3f5a49f85e5f67b09501360751
```

빌드 직후 상태:

```text
redis           healthy
sample-api-1    healthy
sample-api-2    healthy
queue-worker-1  healthy
queue-worker-2  healthy
```

Health 확인:

```text
http://127.0.0.1:8000/health -> 200
http://127.0.0.1:8000/ready  -> 200
http://127.0.0.1:8001/health -> 200
```

로컬 Compose에서는 기존 Redis 컨테이너와 호환되도록 `REDIS_SSL=false`를 명시했습니다.

## 6. Redis 장애 회귀 테스트

Redis 컨테이너를 중지한 상태:

```text
GET  /health          -> HTTP 200 {"status":"ok","service":"sample-fastapi"}
GET  /ready           -> HTTP 503 {"detail":"Redis unavailable"}
POST /api/queue/join  -> HTTP 503 {"detail":"Redis unavailable"}
```

확인 결과:

- FastAPI 프로세스 liveness는 유지됐습니다.
- Redis가 필요한 readiness와 Queue API만 503을 반환했습니다.
- 오류 응답에 Redis Host, URL, Password가 노출되지 않았습니다.
- Redis 재시작 후 `/ready`가 HTTP 200으로 자동 복구됐습니다.

## 7. k6 CPU 부하 테스트

대상 파일: `k6/cpu-load.js`

테스트 조건:

```text
20초 동안 2 VU까지 증가
40초 동안 10 VU까지 증가
20초 동안 0 VU까지 감소
전체 실행 시간 80초
통과 기준: 실패율 < 1%, Checks > 99%, p95 < 3000ms
```

실행 명령:

```powershell
k6 run `
  --summary-export docs/test-results/k6-cpu-load-summary.json `
  -e BASE_URL=http://127.0.0.1:8000 `
  k6/cpu-load.js
```

결과:

| 항목 | 결과 |
| --- | ---: |
| 전체 요청 | 365 |
| 성공 Check | 365 |
| 실패 Check | 0 |
| HTTP 실패율 | 0.00% |
| 평균 응답 시간 | 472.56ms |
| p90 | 897.28ms |
| p95 | 1088.73ms |
| 최대 응답 시간 | 1.30s |
| 최대 VU | 10 |
| 최종 판정 | PASS |

원본 k6 결과: [k6-cpu-load-summary.json](./k6-cpu-load-summary.json)

## 8. k6 Memory 부하 테스트

대상 파일: `k6/memory-load.js`

테스트 조건:

```text
5 VU
전체 실행 시간 60초
통과 기준: 실패율 < 1%, Checks > 99%, p95 < 500ms
```

실행 명령:

```powershell
k6 run `
  --summary-export docs/test-results/k6-memory-load-summary.json `
  -e BASE_URL=http://127.0.0.1:8000 `
  k6/memory-load.js
```

결과:

| 항목 | 결과 |
| --- | ---: |
| 전체 요청 | 300 |
| 성공 Check | 300 |
| 실패 Check | 0 |
| HTTP 실패율 | 0.00% |
| 평균 응답 시간 | 7.50ms |
| p90 | 11.78ms |
| p95 | 15.10ms |
| 최대 응답 시간 | 22.49ms |
| 최대 VU | 5 |
| 최종 판정 | PASS |

원본 k6 결과: [k6-memory-load-summary.json](./k6-memory-load-summary.json)

## 9. 부하 테스트 후 상태

k6 테스트 종료 후에도 API 상태는 정상입니다.

```text
GET /health -> HTTP 200
GET /ready  -> HTTP 200
sample_http_requests_total{path="/api/cpu",status="200"} 365
sample_http_requests_total{path="/api/memory",status="200"} 300
```

부하 종료 후 Docker 상태:

```text
sample-api-1: healthy, 44.08MiB
sample-api-2: healthy, 39.47MiB
```

위 메모리 수치는 부하가 끝난 뒤 회복 상태를 한 번 측정한 값입니다. 테스트 중 Peak CPU·Memory 사용량 증빙은 아니며, Peak 추이는 이후 Prometheus/Grafana 또는 시간대별 `docker stats` 수집을 추가해야 합니다. 이번 k6 결과는 CPU·Memory API에 요청을 가했을 때의 성공률과 응답 시간 증빙입니다.

## 10. 현재 결론과 다음 단계

이번 애플리케이션 사전 단계의 8개 체크 항목과 CPU·Memory k6 테스트는 모두 통과했습니다.

아직 진행하지 않은 다음 단계:

- ElastiCache Terraform 작성
- 실제 AWS ElastiCache 생성 및 TLS 연결
- ECR Repository와 이미지 Push
- Kubernetes Manifest와 EKS 배포
- Prometheus Target 및 KEDA Scale-out/in

기능 단위 반영 원칙에 따라 이번 단계의 애플리케이션 파일과 테스트 결과만 별도 Commit 범위로 관리합니다.
