# Python 3.11 slim 이미지를 사용해 FastAPI 실행에 필요한 최소 기반 이미지를 준비합니다.
FROM python:3.11-slim

# 컨테이너 내부 작업 디렉터리입니다.
# 이후 COPY, RUN, CMD 명령은 이 경로를 기준으로 실행됩니다.
WORKDIR /app

# 의존성 파일을 먼저 복사하면 Docker 빌드 캐시를 효율적으로 사용할 수 있습니다.
COPY requirements.txt .

# 컨테이너 이미지 안에 FastAPI 실행 의존성을 설치합니다.
RUN pip install --no-cache-dir -r requirements.txt

# API와 Worker가 공유하는 애플리케이션 모듈을 복사합니다.
COPY --chown=10001:10001 *.py ./

# 컨테이너를 root 권한으로 실행하지 않도록 전용 사용자를 생성합니다.
RUN groupadd --gid 10001 sampleapp \
    && useradd --uid 10001 --gid sampleapp --no-create-home sampleapp

USER 10001:10001

# FastAPI 앱이 컨테이너 내부에서 8000번 포트를 사용한다는 것을 명시합니다.
EXPOSE 8000

# 컨테이너가 시작될 때 uvicorn으로 FastAPI 앱을 실행합니다.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
