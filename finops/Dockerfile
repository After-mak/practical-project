# Stage 1: download KRR binary
FROM alpine AS krr-downloader
RUN apk add --no-cache curl && \
    curl -L https://github.com/robusta-dev/krr/releases/download/v0.10.0/krr-linux-amd64 -o /usr/local/bin/krr && \
    chmod +x /usr/local/bin/krr

# Stage 2: finops-analyzer app
FROM python:3.11-slim
WORKDIR /app
COPY --from=krr-downloader /usr/local/bin/krr /usr/local/bin/krr
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
