# Stage 1: download & unpack KRR release
# v0.10.0 릴리즈는 GitHub에서 삭제되었고, robusta-krr는 v1.x부터 배포 형식이
# 단일 실행파일(krr-linux-amd64)에서 PyInstaller onedir 압축(zip)으로 바뀌어
# 실행파일(krr)과 그 의존성 폴더(_internal/)가 함께 있어야 동작합니다.
# curl에 -f를 붙여서, 릴리즈 URL이 다시 깨지면(404 등) 빌드가 조용히 "성공"하는 대신
# 명확히 실패하도록 합니다.
FROM alpine AS krr-downloader
ARG KRR_VERSION=v1.29.0
RUN apk add --no-cache curl unzip \
    && curl -fL "https://github.com/robusta-dev/krr/releases/download/${KRR_VERSION}/krr-ubuntu-latest-${KRR_VERSION}.zip" -o /tmp/krr.zip \
    && unzip -q /tmp/krr.zip -d /opt \
    && chmod -R a+rX /opt/krr \
    && chmod +x /opt/krr/krr \
    && rm /tmp/krr.zip

# Stage 2: finops-analyzer app
FROM python:3.11-slim
WORKDIR /app
COPY --from=krr-downloader /opt/krr /opt/krr
ENV PATH="/opt/krr:${PATH}"
COPY finops/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY finops/app ./app

# CIS Benchmark 권고에 따라 컨테이너를 root가 아닌 전용 계정으로 구동
RUN groupadd --system appuser && useradd --system --gid appuser --no-create-home appuser
USER appuser

EXPOSE 8000
# 기본 워커 1개. KRR 결과 캐시(_krr_cache)와 Telegram 승인용 최종 추천값 캐시
# (_last_recommendations)가 프로세스 메모리 안에만 있어서, 워커를 2개 이상으로 올리면
# /analyze를 처리한 워커와 다른 워커가 /recommendation 조회를 받아 "결과 없음"으로 잘못
# 응답하는 경우가 실제로 발생함(테스트로 재현 확인). finops는 하루 1회 CronJob + 가끔 수동
# 호출 정도의 저트래픽 서비스라 워커를 늘려 얻는 처리량 이득보다 이 정합성 문제가 더 크므로
# 기본값을 1로 둠. 정말 처리량이 필요하면 UVICORN_WORKERS를 올리는 대신 캐시를 Redis 등
# 프로세스 외부 저장소로 옮기는 것을 권장.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
