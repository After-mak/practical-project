import requests
from fastapi import FastAPI, Request
import os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

# 💡 발급받은 정보와 세팅값 입력
GITHUB_TOKEN = os.getenv("GITOPS_TOKEN")
GITHUB_OWNER = "After-mak"
GITHUB_REPO = "practical-project" # 인프라,소스코드 저장소 이름

@app.post("/telegram/callback")
async def telegram_callback(request: Request):
    """
    운영자가 텔레그램 인라인 버튼 [승인]을 누르면 
    텔레그램 서버가 이 엔드포인트로 데이터를 쏴줍니다 (Webhook).
    """
    data = await request.json()
    print("텔레그램에서 들어온 신호 데이터:", data)
    
    # 텔레그램 승인 콜백 로직 처리 (예시: callback_query 검증 완료 후)
    # 💡 패턴 분석 시스템이 권장했던 값이 4라고 가정하고 깃허브 액션을 깨웁니다.
    recommended_value = 4 
    
    # GitHub Actions API(Repository Dispatch) 호출용 주소
    github_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 💡 깃허브 액션 스크립트에 정의한 event_type과 client_payload 데이터를 매핑해서 전송
    payload = {
        "event_type": "telegram-approved",
        "client_payload": {
            "recommended_replicas": recommended_value
        }
    }
    
    response = requests.post(github_url, json=payload, headers=headers)
    
    if response.status_code == 204:
        return {"status": "success", "message": "GitHub Actions가 성공적으로 트리거되었습니다!"}
    else:
        return {"status": "failed", "error": response.text}