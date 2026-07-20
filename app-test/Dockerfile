# 1. 초경량 파이썬 이미지 사용 (용량 최소화)
FROM python:3.11-alpine

# 2. 컨테이너 내부 작업 디렉토리 설정
WORKDIR /app

# 3. 패키지 목록 복사 및 설치 (캐시를 지워서 용량 다이어트)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 소스코드와 .env 파일 전체 복사
COPY . .

# 5. FastAPI 서버 실행 명령 (포트 8000 오픈)
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]