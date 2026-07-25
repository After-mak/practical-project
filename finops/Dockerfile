FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# robusta-krr 설치 시 C 네이티브 컴파일이 필요하므로 빌드 도구 설치 후 제거
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
