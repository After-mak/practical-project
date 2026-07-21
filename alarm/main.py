import os
import requests
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FinOps Telegram Deploy & Rollback Gateway")

# ==========================================
# ⚙️ 1. 환경 변수 세팅
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITOPS_TOKEN")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "After-mak")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "practical-project")
TARGET_BRANCH = os.getenv("TARGET_BRANCH", "dev")  # 종원님 명세: ref -> "dev"

GRAFANA_URL = "https://grafana.tuby.shop"

# ==========================================
# 🚀 2. 텔레그램 메시지 발송 헬퍼
# ==========================================
def send_telegram_message(text: str, reply_markup: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"❌ 텔레그램 발송 실패: {e}")

# ==========================================
# 🛠️ 3. GitHub Actions API 호출 헬퍼
# ==========================================
def trigger_github_workflow(workflow_file: str, inputs: dict = None):
    url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/actions/workflows/{workflow_file}/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": TARGET_BRANCH}
    if inputs:
        payload["inputs"] = inputs
        
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"📡 GitHub API [{workflow_file}] 호출 완료 -> 응답 코드: {res.status_code}")
    except Exception as e:
        print(f"❌ GitHub API 호출 에러: {e}")

# ==========================================
# 📊 Pydantic 모델 정의 (FinOps/KRR 스펙 전달용)
# ==========================================
class DeployRequest(BaseModel):
    target_tag: Optional[str] = "v1.2.0"
    current_cpu: Optional[str] = "500m"
    recommended_cpu: Optional[str] = "250m"
    current_mem: Optional[str] = "512Mi"
    recommended_mem: Optional[str] = "256Mi"

class CustomRollbackRequest(BaseModel):
    target_tag: str  # Rollback할 사용자 지정 Target Tag (예: v1.0.0)

# ==========================================
# 🚨 4. Inbound Webhooks
# ==========================================

# ① Alertmanager 수신 (직전 롤백)
@app.post("/webhook/alertmanager")
async def alertmanager_webhook():
    text = (
        "🚨 *[Alertmanager 경고]*\n"
        "mak-app 서비스 에러율 8.5% 돌파! (기준: 1% 이하)\n"
        "최근 리소스 변경/배포로 인한 영향일 수 있습니다. 이전 버전으로 롤백하시겠습니까?"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "⏪ 직전 버전 롤백 (HEAD~1)", "callback_data": "rollback_head"},
            {"text": "🔍 상태 대시보드 확인", "url": GRAFANA_URL}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

# ② FinOps OOMKill 위험 수신 (사용자 지정/권장 롤백)
@app.post("/webhook/finops")
async def finops_webhook(req: Optional[CustomRollbackRequest] = None):
    target_tag = req.target_tag if req else "v1.0.0"
    text = (
        "⚠️ *[FinOps 엔진 분석]*\n"
        "mak-app 리소스 줄임 적용 후 Memory 사용량이 p99 한계치에 다다랐습니다. (OOMKill 위험)\n"
        f"안정성을 위해 이전 안정 버전(`{target_tag}`)으로 롤백을 추천합니다."
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"⏪ 권장 버전({target_tag}) 롤백 실행", "callback_data": f"rollback_custom_{target_tag}"}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

# ③ Argo Rollouts 검증 실패 수신 (즉시 롤백)
@app.post("/webhook/rollouts")
async def rollouts_webhook():
    text = (
        "❌ *[Argo Rollouts 검증 실패]*\n"
        "mak-app 카나리 50% 단계에서 HTTP 5xx 에러가 감지되었습니다.\n"
        "카나리 배포가 중단되었습니다. 승인 후 즉시 Rollback을 진행할까요?"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "⏪ 즉시 롤백 승인", "callback_data": "rollback_head"}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

# ④ KRR 최적화 스펙 시각화 & 사용자 지정/신규 배포 승인 요청 (💡 피드백 반영 파트!)
@app.post("/webhook/deploy-request")
async def deploy_request_webhook(req: DeployRequest):
    text = (
        "💡 *[FinOps / KRR 리소스 최적화 추천]*\n"
        "mak-app 분석 결과 최적의 리소스 스펙 및 배포 타겟이 산출되었습니다.\n\n"
        "📊 *스펙 변경 비교 (values.yaml 반영 예정)*:\n"
        f"• **Target Tag**: `{req.target_tag}`\n"
        f"• **CPU Request**: `{req.current_cpu}` ➡️ *`{req.recommended_cpu}`*\n"
        f"• **Memory Request**: `{req.current_mem}` ➡️ *`{req.recommended_mem}`*\n\n"
        "승인 시 Helm Chart의 `values.yaml` 스펙을 변경하여 자동 배포를 진행합니다."
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"✅ 배포 승인 ({req.target_tag})", "callback_data": f"deploy_approve_{req.target_tag}"},
            {"text": "🔍 대시보드 확인", "url": GRAFANA_URL}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

# ==========================================
# 🔘 5. Outbound Callback (텔레그램 버튼 클릭 수신)
# ==========================================
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
    if "callback_query" in data:
        callback_query = data["callback_query"]
        callback_data = callback_query["data"]
        callback_id = callback_query["id"]
        
        # 버튼 로딩 인디케이터 해제
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": callback_id})
        
        # 🟢 1. [직전 롤백]: rollback.yaml
        if callback_data == "rollback_head":
            send_telegram_message("⏳ *[GitOps]* 직전 버전 원복 파이프라인(`git revert HEAD`)을 시작합니다...")
            background_tasks.add_task(trigger_github_workflow, "rollback.yaml")
            
        # 🔵 2. [사용자 지정/권장 롤백]: rollback-custom.yaml + target_tag
        elif callback_data.startswith("rollback_custom_"):
            target_tag = callback_data.replace("rollback_custom_", "")
            send_telegram_message(f"⏳ *[GitOps]* 지정/권장 버전(`{target_tag}`)으로 롤백 파이프라인을 시작합니다...\n`values.yaml` 내 `image.tag`를 교체합니다.")
            background_tasks.add_task(trigger_github_workflow, "rollback-custom.yaml", {"target_tag": target_tag})
            
        # 🚀 3. [배포 승인]: deploy.yaml + target_tag
        elif callback_data.startswith("deploy_approve_"):
            target_tag = callback_data.replace("deploy_approve_", "")
            send_telegram_message(f"🚀 *[GitOps]* 배포 승인 완료! Helm Chart(`values.yaml`)의 이미지 버전(`{target_tag}`) 및 리소스 스펙 변경 파이프라인을 실행합니다...")
            background_tasks.add_task(trigger_github_workflow, "deploy.yaml", {"target_tag": target_tag})

    return {"status": "ok"}