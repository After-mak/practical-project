import httpx  # 💡 속도와 안정성을 위해 requests 대신 비동기 httpx 사용
from fastapi import FastAPI, Request
import os
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

# 💡 환경변수 및 세팅값
GITHUB_TOKEN = os.getenv("GITOPS_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_OWNER = "After-mak"
GITHUB_REPO = "practical-project" # 인프라,소스코드 저장소 이름

# ==========================================
# 1. [테스트용] 텔레그램으로 승인 버튼 발송하는 엔드포인트
# ==========================================
@app.get("/telegram/send-test")
async def send_test_message(replicas: int = 4):
    """
    브라우저나 Postman으로 http://localhost:8000/telegram/send-test 호출 시 
    텔레그램 방으로 [승인] 버튼이 달린 메시지를 쏴줍니다.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    text = (
        "📊 **패턴 분석 시스템 알림**\n\n"
        f"현재 트래픽 분석 결과, 레플리카 수를 **{replicas}개**로 변경하는 것을 권장합니다.\n"
        "아래 [승인] 버튼을 누르면 배포 파이프라인이 실행됩니다."
    )
    
    # 💡 핵심: 텔레그램 메시지에 인라인 버튼 심기 (callback_data에 추천값 탑승)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "👍 승인", "callback_data": f"approve_{replicas}"},
                    {"text": "❌ 반려", "callback_data": "deny"}
                ]
            ]
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
    return {"message": "텔레그램 메시지 발송 시도", "telegram_response": response.json()}


# ==========================================
# 2. 운영자가 버튼을 눌렀을 때 신호를 받는 웹훅 엔드포인트
# ==========================================
@app.post("/telegram/callback")
async def telegram_callback(request: Request):
    """
    운영자가 텔레그램 인라인 버튼 [승인]을 누르면 
    텔레그램 서버가 이 엔드포인트로 데이터를 쏴줍니다 (Webhook).
    """
    data = await request.json()
    print("텔레그램에서 들어온 신호 데이터:", data)
    
    # 💡 텔레그램이 보낸 callback_query 구조에서 데이터 안전하게 파싱
    callback_query = data.get("callback_query", {})
    callback_data = callback_query.get("data", "")  # 예: "approve_4"
    
    # 만약 [승인] 버튼을 누른 게 아니라면 무시
    if not callback_data.startswith("approve_"):
        return {"status": "ignored", "message": "승인 신호가 아닙니다."}
    
    # "approve_4" 문자열에서 숫자 '4'만 쏙 뽑아내기
    recommended_value = int(callback_data.split("_")[1])
    
    # GitHub Actions API(Repository Dispatch) 호출용 주소
    github_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",  # token 대신 Bearer 스펙 권장
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # 깃허브 액션 스크립트에 정의한 event_type과 client_payload 데이터를 매핑해서 전송
    payload = {
        "event_type": "telegram-approved",
        "client_payload": {
            "recommended_replicas": recommended_value
        }
    }
    
    # 비동기로 안전하게 GitHub Actions 트리거
    async with httpx.AsyncClient() as client:
        response = await client.post(github_url, json=payload, headers=headers)
    
    if response.status_code == 204:
        return {"status": "success", "message": f"GitHub Actions가 성공적으로 트리거되었습니다! (값: {recommended_value})"}
    else:
        return {"status": "failed", "error": response.text}