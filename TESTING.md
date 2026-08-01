# 테스트 가이드

> Queue 기능은 더 이상 프로세스 인메모리 값을 사용하지 않고 Redis를 사용합니다. Queue·Readiness·Metrics 통합 테스트는 저장소 루트의 `docker-compose.yml`과 `docs/redis-queue-runbook.md`를 기준으로 실행합니다. 기존 단일 FastAPI 실행 방식은 `/health`와 워크로드 API 확인 용도로만 사용할 수 있으며, Redis가 없으면 `/ready`, Queue API와 `/metrics`가 503을 반환하는 것이 정상입니다.

이 문서는 팀원이 샘플 FastAPI 애플리케이션을 로컬 또는 Docker로 실행하고, API 기능과 k6 부하 테스트를 확인하는 절차를 설명합니다.

테스트는 다음 순서로 진행하는 것을 권장합니다.

1. FastAPI 로컬 실행
2. API 기능 확인
3. Docker 실행 확인
4. k6 일반 부하 테스트
5. CPU, 메모리 및 혼합 부하 테스트

CPU와 메모리 테스트는 시스템 사용량을 크게 높일 수 있습니다. 공용 개발 서버에서는 팀원과 실행 시간을 협의한 후 진행하세요.

## 1. 사전 준비

필수 도구:

- Git
- Python 3.11 이상
- k6
- Docker Desktop 또는 Docker Engine(Docker 테스트를 진행할 경우)

설치 여부를 확인합니다.

```powershell
python --version
k6 version
docker --version
```

모든 명령은 별도 설명이 없다면 프로젝트 루트에서 실행합니다.

```powershell
cd D:\sil-p\practical-project
```

Linux/macOS에서는 저장소를 복제한 실제 경로로 이동합니다.

```bash
cd /path/to/practical-project
```

## 2. FastAPI 로컬 실행

### Windows PowerShell

```powershell
cd .\apps\sample-fastapi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

PowerShell 실행 정책으로 가상환경 활성화가 차단되면 현재 터미널에서만 임시로 허용합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Linux/macOS

```bash
cd ./apps/sample-fastapi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

8000번 포트를 이미 사용 중이라면 `--port 8010`으로 변경합니다.

서버가 시작되면 다음 주소를 확인할 수 있습니다.

- 헬스체크: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>

## 3. API 기능 확인

서버를 실행한 터미널은 그대로 두고 새 터미널에서 요청합니다.

### Windows PowerShell

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/api/normal
curl.exe http://127.0.0.1:8000/api/cpu
curl.exe http://127.0.0.1:8000/api/memory
curl.exe http://127.0.0.1:8000/api/slow
curl.exe http://127.0.0.1:8000/api/error
```

### Linux/macOS

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/normal
curl http://127.0.0.1:8000/api/cpu
curl http://127.0.0.1:8000/api/memory
curl http://127.0.0.1:8000/api/slow
curl http://127.0.0.1:8000/api/error
```

확인 기준:

| API | 기대 결과 |
| --- | --- |
| `GET /health` | HTTP 200과 `status: ok` 반환 |
| `GET /api/normal` | HTTP 200과 정상 메시지 반환 |
| `GET /api/cpu` | 계산 결과를 반환하고 CPU 사용량이 일시적으로 증가 |
| `GET /api/memory` | `items: 100000`을 반환하고 메모리 사용량이 일시적으로 증가 |
| `GET /api/slow` | 약 2초 후 HTTP 200 반환 |
| `GET /api/error` | 약 30% 확률로 HTTP 500, 나머지는 HTTP 200 반환 |

`/api/error`의 간헐적인 HTTP 500은 장애 상황을 재현하기 위한 의도된 동작입니다. 또한 `/`와 `/favicon.ico`는 구현하지 않았으므로 HTTP 404가 정상입니다.

## 4. Docker 테스트

로컬 Uvicorn 서버가 실행 중이라면 먼저 `Ctrl+C`로 종료해 포트 충돌을 방지합니다.

프로젝트 루트에서 이미지를 빌드하고 실행합니다.

```powershell
docker build -t sample-fastapi:local .\apps\sample-fastapi
docker run --rm --name sample-fastapi -p 8000:8000 sample-fastapi:local
```

Linux/macOS에서는 빌드 경로를 다음과 같이 사용할 수 있습니다.

```bash
docker build -t sample-fastapi:local ./apps/sample-fastapi
docker run --rm --name sample-fastapi -p 8000:8000 sample-fastapi:local
```

새 터미널에서 컨테이너 상태와 API를 확인합니다.

```powershell
docker ps
docker logs sample-fastapi
curl.exe http://127.0.0.1:8000/health
```

Linux/macOS에서는 마지막 명령의 `curl.exe`를 `curl`로 변경합니다.

헬스체크가 HTTP 200을 반환하면 Docker 테스트를 통과한 것입니다. 컨테이너는 실행 터미널에서 `Ctrl+C`를 눌러 종료합니다.

## 5. k6 부하 테스트

FastAPI 또는 Docker 컨테이너가 `http://127.0.0.1:8000`에서 실행 중이어야 합니다. k6 명령은 프로젝트 루트의 새 터미널에서 실행합니다.

### 5.1 일반 요청 테스트

```powershell
k6 run .\k6\normal-load.js
```

Linux/macOS:

```bash
k6 run ./k6/normal-load.js
```

테스트 조건:

- 가상 사용자가 최대 10명까지 단계적으로 증가
- 총 실행 시간 6분
- `/api/normal` 호출

기본 통과 기준:

- `checks` 성공률 100%
- `http_req_failed` 0%
- 모든 응답이 HTTP 200

### 5.2 메모리 부하 테스트

```powershell
k6 run .\k6\memory-load.js
```

- 가상 사용자 5명이 1분 동안 `/api/memory`를 호출합니다.
- 요청마다 메모리를 일시적으로 많이 사용하므로 시스템 상태를 확인하면서 실행합니다.
- Docker 환경에서는 `docker stats sample-fastapi`로 사용량을 관찰할 수 있습니다.

### 5.3 CPU 스파이크 테스트

```powershell
k6 run .\k6\cpu-load.js
```

가상 사용자가 `2명 → 10명 → 0명` 순서로 변하면서 `/api/cpu`를 호출합니다. CPU 포화로 응답 시간이 증가할 수 있으므로 `http_req_duration`, `http_req_failed`와 CPU 사용량을 함께 확인합니다.

### 5.4 Smoke 및 Queue 스케일링 테스트

```powershell
k6 run .\k6\smoke.js
k6 run -e QUEUE_RATE=20 -e TEST_DURATION=2m .\k6\queue-scale-out.js
k6 run -e TEST_DURATION=2m .\k6\queue-scale-in.js
```

`smoke.js`는 핵심 API와 메트릭을 한 번씩 확인합니다. `queue-scale-out.js`는 Worker 처리량보다 빠르게 Redis Queue를 증가시키고, `queue-scale-in.js`는 Worker가 Queue를 0까지 비우는지 확인합니다.

## 6. 포트 또는 대상 서버 변경

서버를 8010번 포트에서 실행한 경우 PowerShell에서 다음과 같이 지정합니다.

```powershell
$env:BASE_URL = "http://127.0.0.1:8010"
k6 run .\k6\normal-load.js
Remove-Item Env:BASE_URL
```

Linux/macOS:

```bash
BASE_URL=http://127.0.0.1:8010 k6 run ./k6/normal-load.js
```

개발 서버나 로드밸런서를 테스트할 때도 `BASE_URL`을 해당 주소로 변경합니다. CPU 및 메모리 테스트는 다른 사용자가 이용하는 환경에 예고 없이 실행하지 마세요.

## 7. 테스트 결과 공유

문제가 발생하면 다음 정보를 팀에 함께 공유합니다.

- 실행한 테스트 파일과 명령어
- 테스트 대상 `BASE_URL`
- 실행 일시와 실행 환경(로컬, Docker 또는 개발 서버)
- k6 결과의 `checks`, `http_req_failed`, `http_req_duration`
- FastAPI 또는 Docker 로그
- CPU와 메모리 사용량

k6 결과를 파일로 남겨야 하는 경우 다음과 같이 실행할 수 있습니다.

```powershell
k6 run --summary-export k6-summary.json .\k6\normal-load.js
```

`k6-summary.json`에는 테스트 대상이나 실행 환경에 관한 정보가 포함될 수 있으므로 커밋하기 전에 내용을 확인합니다.

## 8. 종료 및 정리

- Uvicorn 또는 Docker 실행 터미널에서 `Ctrl+C`를 누릅니다.
- Python 가상환경은 `deactivate`로 종료합니다.
- PowerShell에서 설정한 `BASE_URL`은 `Remove-Item Env:BASE_URL`로 제거합니다.
