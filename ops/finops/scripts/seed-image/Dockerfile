# KRR 더미 이력 데이터 시딩용 Prometheus initContainer 이미지.
# python3(더미 데이터 생성) + promtool(TSDB 블록 생성) + kubectl(실제 파드 이름 조회)만 필요한
# 최소 구성입니다. Prometheus 메인 컨테이너보다 먼저 실행되어 공유 볼륨에 데이터를 채웁니다.
FROM python:3.12-slim

ARG PROMETHEUS_VERSION=2.55.1
ARG KUBECTL_VERSION=v1.33.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fL "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz" \
       -o /tmp/prometheus.tar.gz \
    && tar xzf /tmp/prometheus.tar.gz -C /tmp \
    && mv "/tmp/prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool" /usr/local/bin/promtool \
    && chmod +x /usr/local/bin/promtool \
    && curl -fL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
       -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && rm -rf /tmp/prometheus* \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 10001 -r -s /sbin/nologin seeduser
WORKDIR /opt/krr-seed
COPY generate_krr_dummy_history.py seed_init_entrypoint.sh /opt/krr-seed/
RUN chmod +x /opt/krr-seed/seed_init_entrypoint.sh \
    && chown -R seeduser /opt/krr-seed

USER seeduser
ENTRYPOINT ["/bin/sh", "/opt/krr-seed/seed_init_entrypoint.sh"]
