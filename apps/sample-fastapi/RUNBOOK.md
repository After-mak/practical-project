# Sample FastAPI 로컬 실행 가이드

> 현재 Queue는 Redis 공유 Queue를 사용합니다. `/ready`, Queue API와 `/metrics`를 정상적으로 사용하려면 Redis가 먼저 실행되어야 합니다. 가장 간단한 전체 실행 방법은 저장소 루트에서 `docker compose up -d --build redis sample-api-1 sample-api-2`를 실행하는 것입니다. Worker는 `docker compose --profile worker up -d --scale queue-worker=2 queue-worker`로 별도 실행합니다. 상세 내용은 `docs/redis-queue-runbook.md`를 참고합니다.

이 문서는 샘플 FastAPI 앱을 로컬에서 실행하고 확인하는 방법을 정리합니다.

Windows PowerShell과 Linux/macOS는 가상환경 활성화 명령이 다르므로 구분해서 실행해야 합니다.

## 1. 공통 준비

프로젝트 루트에서 샘플 앱 폴더로 이동합니다.

### Windows PowerShell

```powershell
cd D:\sil-p\practical-project\apps\sample-fastapi
```

또는 프로젝트 루트에 이미 있다면 아래처럼 이동해도 됩니다.

```powershell
cd .\apps\sample-fastapi
```

### Linux/macOS

```bash
cd /path/to/practical-project/apps/sample-fastapi
```

프로젝트 루트에 이미 있다면 아래처럼 이동해도 됩니다.

```bash
cd ./apps/sample-fastapi
```

## 2. Windows PowerShell에서 실행

가상환경을 만듭니다.

```powershell
python -m venv .venv
```

가상환경을 활성화합니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

프롬프트 앞에 `(.venv)`가 보이면 활성화된 상태입니다.

패키지를 설치합니다.

```powershell
pip install -r requirements.txt
```

FastAPI 서버를 실행합니다.

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

8000번 포트에서 권한 오류나 포트 충돌이 나면 8010번 포트로 실행합니다.

```powershell
uvicorn main:app --host 127.0.0.1 --port 8010 --reload
```

## 3. Linux/macOS에서 실행

가상환경을 만듭니다.

```bash
python3 -m venv .venv
```

가상환경을 활성화합니다.

```bash
source .venv/bin/activate
```

프롬프트 앞에 `(.venv)`가 보이면 활성화된 상태입니다.

패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

FastAPI 서버를 실행합니다.

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

8000번 포트가 이미 사용 중이면 8010번 포트로 실행합니다.

```bash
uvicorn main:app --host 127.0.0.1 --port 8010 --reload
```

## 4. API 동작 확인

서버 실행 창은 그대로 두고, 새 터미널을 열어 확인합니다.

8000번 포트로 실행한 경우:

### Windows PowerShell

```powershell
curl http://127.0.0.1:8000/health
```

### Linux/macOS

```bash
curl http://127.0.0.1:8000/health
```

8010번 포트로 실행한 경우:

### Windows PowerShell

```powershell
curl http://127.0.0.1:8010/health
```

### Linux/macOS

```bash
curl http://127.0.0.1:8010/health
```

정상 응답 예시는 아래와 같습니다.

```json
{"status":"ok","service":"sample-fastapi"}
```

## 5. Swagger 문서 확인

브라우저에서 아래 주소로 접속합니다.

8000번 포트로 실행한 경우:

```text
http://127.0.0.1:8000/docs
```

8010번 포트로 실행한 경우:

```text
http://127.0.0.1:8010/docs
```

## 6. 참고 로그

브라우저로 `/` 또는 `/favicon.ico`에 접속하면 아래처럼 404 로그가 보일 수 있습니다.

```text
GET / HTTP/1.1" 404 Not Found
GET /favicon.ico HTTP/1.1" 404 Not Found
```

현재 앱에는 `/`와 `/favicon.ico` 라우트를 만들지 않았기 때문에 정상적인 로그입니다.

실제 테스트는 `/health` 또는 `/docs` 주소로 진행합니다.

## 7. 서버 종료

FastAPI 서버를 실행 중인 터미널에서 아래 키를 누릅니다.

```text
Ctrl + C
```

## 8. 가상환경 종료

작업이 끝나면 가상환경을 비활성화합니다.

### Windows PowerShell

```powershell
deactivate
```

### Linux/macOS

```bash
deactivate
```

## 9. Docker 실행

Docker가 설치되어 있다면 프로젝트 루트에서 이미지를 빌드합니다.

### Windows PowerShell

```powershell
cd D:\sil-p\practical-project
docker build -t sample-fastapi:local apps/sample-fastapi
```

### Linux/macOS

```bash
cd /path/to/practical-project
docker build -t sample-fastapi:local apps/sample-fastapi
```

컨테이너를 실행합니다.

```bash
docker run --rm -p 8000:8000 sample-fastapi:local
```

호스트의 8000번 포트가 이미 사용 중이면 아래처럼 8010번으로 연결합니다.

```bash
docker run --rm -p 8010:8000 sample-fastapi:local
```
