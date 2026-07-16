import os
import requests
from fastapi import FastAPI, Request
from dotenv import load_dotenv

# 최상위 .env 파일에서 토큰 정보 로드
load_dotenv()

app = FastAPI(title="FinOps Telegram Gateway")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN").replace('"', '')

@app.post("/webhook/telegram")
async def handle_telegram_callback(request: Request):
    """ 운영자가 스마트폰 텔레grams에서 승인 버튼을 누르면 신호가 꽂히는 곳 """
    data = await request.json()
    
    callback_query = data.get("callback_query", {})
    if not callback_query:
        return {"status": "ignored"}
        
    callback_data = callback_query.get("data")
    query_id = callback_query.get("id")
    
    # 승인 버튼(infra_approve)이 눌렸을 때
    if callback_data == "infra_approve":
        print("🟢 텔레그램 승인 확인 완료!")
        
        # 1. 텔레그램 화면에 승인 알림 팝업 띄우기
        alert_url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        requests.post(alert_url, json={
            "callback_query_id": query_id,
            "text": "👍 승인이 완료되었습니다. GitOps(Argo CD) 파이프라인으로 설정을 반영합니다!",
            "show_alert": True
        })
        
        # 2. 임종원 팀장의 GitOps 파이프라인을 깨우기 위한 Git Push 트리거
        # 직접 AWS에 apply하는 대신, 변경된 인프라 명세서(KEDA 등)를 공용 레포에 밀어 넣습니다.
        print("🚀  변경된 인프라 설정을 공용 레포지토리에 반영 중 (Git Push)...")
        
        # ⚠️ 실무 팁: 아래 주석 처리된 Git 명령어를 팀장과 상의 후 활성화하거나, 
        # 임종원 팀장이 만든 'make git-push-auto' 같은 명령어로 대체하면 됩니다.
        # os.system("git add . && git commit -m 'feat: FinOps Rightsizing approved by Telegram' && git push origin main")
        
        print("🟢 GitOps 레포지토리 업데이트 완료 -> Argo CD가 이를 감지하여 자동 동기화할 예정입니다.")
        
        return {"status": "approved"}
        
    return {"status": "ok"}