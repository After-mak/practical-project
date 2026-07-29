FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/huggingface \
    TRANSFORMERS_CACHE=/tmp/huggingface

COPY chronos/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY chronos/chronos_prometheus.py chronos/app.py ./

RUN groupadd --system chronos \
    && useradd --system --gid chronos --no-create-home chronos \
    && mkdir -p /tmp/huggingface \
    && chown -R chronos:chronos /app /tmp/huggingface

USER chronos

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
