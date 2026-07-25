# ── Stage 1: KRR 전용 빌드 ──────────────────────────────────────────────────
# python:3.11 (full) 이미지는 gcc 등 빌드 도구가 내장되어 있어
# robusta-krr의 네이티브 의존성 컴파일이 가능합니다.
FROM python:3.11 AS krr-builder

# KRR을 격리된 venv에 설치 (앱의 pydantic v2와 충돌 방지)
RUN python -m venv /opt/krr && \
    /opt/krr/bin/pip install --no-cache-dir robusta-krr

# ── Stage 2: finops-analyzer 앱 ─────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# KRR venv만 복사하고 krr 커맨드를 PATH에 노출
COPY --from=krr-builder /opt/krr /opt/krr
RUN ln -sf /opt/krr/bin/krr /usr/local/bin/krr

# 앱 의존성 설치 (KRR과 완전히 독립된 환경 — pydantic v2 사용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
