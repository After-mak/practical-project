# Sample FastAPI 브랜치 작업 정리

## 1. 문서 목적

이 문서는 `feature/sample-fastapi` 브랜치에서 진행한 FastAPI 샘플 애플리케이션, Docker 실행 환경, k6 부하 테스트, Queue Length 기반 KEDA 검증 기능과 관련 문서 작업을 정리합니다.

현재 작업은 다음 두 상태로 구분됩니다.

1. `feature/sample-fastapi` 브랜치에 반영된 기본 기능
2. 같은 브랜치에 후속으로 반영한 Queue/KEDA 추가 기능

## 2. Git 브랜치 상태

현재 브랜치:

```text
feature/sample-fastapi
```

기본 FastAPI와 k6 테스트를 반영한 커밋:

```text
db28140 feat: FastAPI 샘플 및 k6 부하 테스트 추가
```

Queue API, Prometheus 메트릭, KEDA 테스트 및 문서 작업은 후속 변경으로 `feature/sample-fastapi` 브랜치에 함께 반영했습니다.

## 3. 원격 브랜치에 반영된 작업

### 3.1 FastAPI 기본 API

파일:

```text
apps/sample-fastapi/main.py
```

구현된 API:

| Method | Endpoint | 역할 |
| --- | --- | --- |
| `GET` | `/health` | 컨테이너 및 Kubernetes 상태 확인 |
| `GET` | `/api/normal` | 일반적인 정상 요청 반환 |
| `GET` | `/api/cpu` | 반복 계산을 통한 CPU 부하 생성 |
| `GET` | `/api/memory` | 일시적인 메모리 부하 생성 |
| `GET` | `/api/slow` | 의도적인 2초 지연 응답 |
| `GET` | `/api/error` | 약 30% 확률로 오류 발생 |

### 3.2 Python 실행 환경

파일:

```text
apps/sample-fastapi/requirements.txt
```

의존성:

```text
fastapi==0.115.6
uvicorn[standard]==0.34.0
```

### 3.3 Docker 실행 환경

파일:

```text
apps/sample-fastapi/Dockerfile
```

구성 내용:

- Python 3.11 slim 이미지 사용
- 컨테이너 작업 디렉터리 `/app`
- FastAPI/Uvicorn 의존성 설치
- 컨테이너 포트 `8000` 사용
- Uvicorn으로 FastAPI 애플리케이션 실행

로컬 이미지 빌드 및 실행 예시:

```bash
docker build -t sample-fastapi:local apps/sample-fastapi
docker run --rm -p 8000:8000 sample-fastapi:local
```

### 3.4 기본 k6 부하 테스트

| 파일 | 목적 | 실행 조건 |
| --- | --- | --- |
| `smoke.js` | 핵심 API와 메트릭 확인 | VU 1명, 1회 |
| `normal-load.js` | 정상 API 기준 부하 생성 | 최대 VU 10명, 6분 |
| `cpu-load.js` | CPU 사용량 급증 재현 | 최대 VU 10명 |
| `memory-load.js` | 메모리 사용량 증가 재현 | VU 5명, 1분 |
| `soak.js` | 장시간 안정성 확인 | 기본 VU 10명, 30분 |

모든 k6 스크립트는 다음 환경변수를 지원합니다.

```javascript
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
```

로컬 실행 예시:

```bash
k6 run k6/normal-load.js
```

EKS/Ingress 실행 예시:

```bash
k6 run -e BASE_URL=http://<ingress-url> k6/normal-load.js
```

### 3.5 실행 및 테스트 문서

작성된 문서:

```text
TESTING.md
apps/sample-fastapi/RUNBOOK.md
```

주요 내용:

- Windows PowerShell 및 Linux/macOS 실행 방법
- Python 가상환경 구성
- Uvicorn 실행 방법
- Swagger와 API 확인 방법
- Docker 이미지 빌드 및 실행 방법
- k6 테스트별 실행 방법과 통과 기준
- 다른 포트 및 원격 서버 테스트 방법
- 테스트 결과 공유 항목

### 3.6 Git 제외 설정

`.gitignore`에 다음 항목을 추가했습니다.

```gitignore
__pycache__/
*.pyc
.venv/
.vscode/
```

## 4. Queue/KEDA 후속 작업

### 4.1 Queue API

`apps/sample-fastapi/main.py`에 Queue Length 기반 KEDA 테스트용 API를 추가했습니다.

| Method | Endpoint | 역할 |
| --- | --- | --- |
| `POST` | `/api/queue/join` | Queue Length 1 증가 |
| `POST` | `/api/queue/process` | Queue Length 1 감소 |
| `GET` | `/api/queue/status` | 현재 Queue Length 반환 |

구현 특징:

- Queue 상태는 FastAPI 프로세스 메모리에 저장
- Redis와 외부 데이터베이스를 사용하지 않음
- Queue Length는 0보다 작아지지 않음
- 동시에 여러 요청이 들어올 수 있어 Python `Lock`으로 상태 보호

응답 예시:

```json
{
  "message": "joined queue",
  "queue_length": 10
}
```

### 4.2 Prometheus 메트릭

추가된 API:

```text
GET /metrics
```

제공 메트릭:

```text
# HELP sample_queue_length Current sample queue length
# TYPE sample_queue_length gauge
sample_queue_length 9
```

특징:

- Prometheus text exposition 형식
- Content-Type: `text/plain; version=0.0.4`
- `/api/queue/status`와 동일한 Queue Length 제공
- Prometheus 기반 KEDA Trigger에서 사용 가능

### 4.3 KEDA 검증용 k6 테스트

#### queue-scale-out.js

목적:

- `/api/queue/join` 반복 호출
- Queue Length 빠른 증가
- KEDA Scale-Out 조건 생성

실행 방식:

```text
기본 초당 등록: 20건
기본 실행 시간: 2분
QUEUE_RATE와 TEST_DURATION 환경변수로 조정
```

#### queue-scale-in.js

목적:

- `/api/queue/status` 주기적 조회
- Redis Worker의 Queue 소진 관찰
- KEDA Scale-In 조건 생성

실행 조건:

```text
VU 1명
기본 실행 시간 2분
종료 시 Queue Length 0을 Threshold로 검사
```

#### karpenter-stress.js

목적:

- 높은 Queue 등록률로 KEDA Worker Pod 확장 유도
- Pending Pod를 만들어 Karpenter Node 확장 검증 입력 제공

동작 방식:

```text
기본 초당 Queue 등록: 100건
작업당 처리 시간: 1초
QUEUE_RATE와 TEST_DURATION 환경변수로 조정
```

실행 단계:

```text
기본 실행 시간: 5분
constant-arrival-rate executor 사용
```

주요 실행 로직에는 팀원들이 쉽게 이해할 수 있도록 줄별 주석을 추가했습니다.

## 5. 협업 및 인수인계 문서

### 5.1 샘플 앱/부하 테스트 시나리오

파일:

```text
docs/sample-app-loadtest-scenario.md
```

포함 내용:

- 샘플 앱의 목적과 전체 API 목록
- k6 테스트 파일 목록과 테스트별 목적
- 로컬 및 EKS/Ingress 환경 실행 방법
- 워크로드별 추천 테스트 매핑
- KEDA Scale-Out/Scale-In 검증 시나리오
- Karpenter 노드 증설 검증 시나리오
- Chronos-2 시계열 예측 검증 시나리오
- 테스트 결과 공유 항목

### 5.2 Kubernetes 워크로드 요구사항

파일:

```text
docs/workload-requirements.md
```

포함 내용:

- 권장 Namespace: `finops-demo`
- 공통 및 워크로드별 Label
- 워크로드별 CPU/Memory requests와 limits
- 초기 replica 권장값
- 컨테이너 포트 `8000`
- `/health` Readiness/Liveness Probe
- ECR 이미지 태그 형식
- Service 및 Ingress 요구사항
- Prometheus `/metrics` 수집 요구사항
- KEDA 연동 시 고려사항
- KRR/Prometheus 관측 요구사항
- Helm/GitOps 담당자 인계 체크리스트

## 6. 워크로드별 테스트 매핑

| 워크로드 | 목적 | 추천 테스트 |
| --- | --- | --- |
| `baseline-app` | 정상 사용량 기준선 확보 | `normal-load.js` |
| `overallocated-app` | 실제 사용량보다 과도한 requests 재현 | 낮은 VU의 `normal-load.js`, `soak.js` |
| `idle-app` | 요청이 거의 없는 유휴 상태 재현 | 부하 테스트를 실행하지 않음 |
| `spike-app` | 특정 시점 CPU 사용량 급증 재현 | `cpu-load.js` |
| KEDA 대상 앱 | Queue Length 기반 Scale-Out/Scale-In | Queue 테스트 3종 |

## 7. 로컬 검증 결과

Docker 환경에서 실제 애플리케이션과 Queue API를 검증했습니다.

### API 검증

| 항목 | 결과 |
| --- | --- |
| Docker 이미지 빌드 | 성공 |
| 컨테이너 실행 | 성공 |
| `/health` | 정상 |
| Queue 초기값 | `0` |
| join 2회 | `1 → 2` |
| process 1회 | `2 → 1` |
| Queue Length 하한 | `0` 유지 |
| `/metrics`와 Queue 상태 | 일치 |
| Prometheus Content-Type | 정상 |
| OpenAPI 신규 경로 | 등록 확인 |

### k6 smoke 테스트

| 테스트 | 요청 수 | Check 성공률 | HTTP 실패율 |
| --- | ---: | ---: | ---: |
| Queue 증가 | 6 | 100% | 0% |
| Queue 소비 | 50 | 100% | 0% |
| KEDA 혼합 | 6 | 100% | 0% |

추가 검증:

- Python 구문 검사 통과
- 전체 k6 파일 로딩 검사 통과
- k6 실행 후 `/api/queue/status`와 `/metrics` 값 일치
- 테스트 컨테이너 종료 및 정리 완료

위 k6 결과는 기능 확인을 위한 짧은 smoke 테스트입니다. 스크립트에 정의된 전체 실행 시간의 장시간 부하 테스트는 아직 수행하지 않았습니다.

## 8. EKS 테스트 준비사항

현재 저장소에는 Kubernetes Deployment, Service, Ingress, ServiceMonitor 및 KEDA ScaledObject가 포함되어 있지 않습니다. 실제 EKS 테스트 전 K8s 담당자의 클러스터·Add-on 구성과 환경별 이미지 주소, Prometheus 주소를 확정한 뒤 Manifest를 새로 작성해야 합니다.

1. 샘플 앱 Docker 이미지를 ECR에 푸시
2. `finops-demo` Namespace에 Deployment와 Service 배포
3. Ingress 또는 LoadBalancer 주소 준비
4. Prometheus에서 `/metrics` 수집
5. `sample_queue_length`를 조회하는 KEDA Prometheus Trigger 구성
6. KEDA ScaledObject와 HPA 상태 확인
7. Ingress 주소를 k6의 `BASE_URL`로 전달

EKS 실행 예시:

```bash
k6 run -e BASE_URL=http://<ingress-url> -e QUEUE_RATE=20 k6/queue-scale-out.js
k6 run -e BASE_URL=http://<ingress-url> k6/queue-scale-in.js
k6 run -e BASE_URL=http://<ingress-url> -e QUEUE_RATE=100 k6/karpenter-stress.js
```

## 9. 현재 구현의 제약사항

Queue Length는 Redis 공유 Queue의 `LLEN`으로 조회합니다. 다만 Worker는 계획에 따라 `BLPOP`을 사용하므로 작업을 가져온 직후 비정상 종료하면 해당 작업을 잃을 수 있습니다.

따라서 다음 제약이 있습니다.

- Pod가 재시작되면 Queue Length가 0으로 초기화됨
- replica가 여러 개면 Pod별 Queue Length가 서로 다름
- 실제 공유 Queue의 정확한 처리 상태를 표현하지 못함
- 초기 KEDA/Prometheus 연동 데모 용도로만 적합함

여러 Pod의 Queue Length를 KEDA에서 사용하려면 Prometheus 쿼리를 다음처럼 집계하는 방식을 담당자와 협의해야 합니다.

```promql
sum(sample_queue_length{namespace="finops-demo"})
```

실제 서비스 수준의 Queue가 필요하면 Redis 등의 외부 저장소로 교체해야 합니다.

## 10. 다음 작업

- [x] Queue/KEDA 관련 변경 사항 코드 리뷰
- [x] 변경 파일 Git 커밋
- [x] `feature/sample-fastapi` 원격 브랜치 푸시
- [ ] ECR 이미지 빌드 및 푸시
- [ ] Helm/GitOps 담당자에게 워크로드 요구사항 전달
- [ ] Prometheus에서 `sample_queue_length` 수집 확인
- [ ] KEDA ScaledObject 적용 후 Scale-Out 확인
- [ ] Queue 소비 후 Scale-In 확인
- [ ] 전체 실행 시간 기준 k6 부하 테스트 수행
