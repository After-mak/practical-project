# 1. 파이썬 기본 환경 준비
FROM python:3.11-slim

# 2. 작업할 디렉토리 설정
WORKDIR /app

# 3. 민규 님의 requirements.txt 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. alarm 폴더 안의 모든 코드(main.py, send_report.sh 등) 복사
COPY . .

# 5. FastAPI 서버 실행 (현재 폴더에 main.py가 있으므로 main:app으로 실행)
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]