import os
import requests
from typing import Optional
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv

# ==========================================
# ⚙️ 1. 환경 변수 세팅 (.env 상위/현재 자동 탐색)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_alarm = os.path.join(BASE_DIR, ".env")
env_root = os.path.join(os.path.dirname(BASE_DIR), ".env")

# alarm/.env 가 없으면 최상위 .env 자동 로드
if os.path.exists(env_alarm):
    load_dotenv(env_alarm)
elif os.path.exists(env_root):
    load_dotenv(env_root)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITOPS_TOKEN")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "After-mak")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "practical-project")
TARGET_BRANCH = os.getenv("TARGET_BRANCH", "dev")

GRAFANA_URL = "http://tuby.shop:3000"

# 🔍 .env 로딩 여부 터미널 점검 로그
print("--------------------------------------------------")
print(f"🔑 TELEGRAM_BOT_TOKEN 로드 상태: {'✅ 성공' if TELEGRAM_BOT_TOKEN else '❌ 실패 (None)'}")
print(f"🆔 TELEGRAM_CHAT_ID 로드 상태: {'✅ 성공' if TELEGRAM_CHAT_ID else '❌ 실패 (None)'}")
print("--------------------------------------------------")

app = FastAPI(title="FinOps Telegram Alert Gateway")

# ==========================================
# 📊 Pydantic 모델 정의
# ==========================================
class DeployRequest(BaseModel):
    target_tag: Optional[str] = "v1.2.0"
    current_cpu: Optional[str] = "500m"
    recommended_cpu: Optional[str] = "250m"
    current_mem: Optional[str] = "512Mi"
    recommended_mem: Optional[str] = "256Mi"

class CustomRollbackRequest(BaseModel):
    target_tag: Optional[str] = "v1.0.0"

# ==========================================
# 🛠️ Helper 함수들
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
        res = requests.post(url, json=payload, timeout=5)
        print(f"📲 Telegram 전송 결과 -> 응답 코드: {res.status_code}")
        if res.status_code != 200:
            print(f"❌ Telegram 전송 실패 상세: {res.text}")
    except Exception as e:
        print(f"❌ Telegram 전송 에러: {e}")

def update_telegram_message(chat_id: int, message_id: int, new_text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"❌ Telegram 메시지 수정 에러: {e}")

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
        
        if res.status_code not in [200, 201, 202, 204]:
            send_telegram_message(
                f"🚨 *[GitHub Actions 호출 실패]*\n"
                f"• Workflow: `{workflow_file}`\n"
                f"• HTTP 상태코드: `{res.status_code}`\n"
                f"• 토큰/권한 및 `.env` 설정을 확인하세요."
            )
    except Exception as e:
        print(f"❌ GitHub API 호출 에러: {e}")
        send_telegram_message(f"🚨 *[GitHub API 통신 에러]*: `{e}`")

# ==========================================
# 📩 Webhook Endpoints (총 5개)
# ==========================================
@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request):
    """1️⃣ Alertmanager 리소스 임계치 초과 알림 (실제 페이로드 파싱)"""
    payload = await request.json()
    alerts = payload.get("alerts", [])
    if not alerts:
        return {"status": "ignored", "reason": "no alerts in payload"}

    lines = []
    any_firing = False
    for alert in alerts:
        status = alert.get("status", "unknown")
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alertname = labels.get("alertname", "UnknownAlert")
        severity = labels.get("severity", "unknown")
        summary = annotations.get("summary") or annotations.get("description") or "설명 없음"
        icon = "🚨" if status == "firing" else "✅"
        lines.append(f"{icon} *{alertname}* ({severity}) - {status}\n{summary}")
        if status == "firing":
            any_firing = True

    text = "*[Alertmanager 알림]*\n\n" + "\n\n".join(lines)
    reply_markup = None
    if any_firing:
        text += "\n\n최근 리소스 변경/배포로 인한 영향일 수 있습니다. 이전 버전으로 롤백하시겠습니까?"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "⏪ 직전 버전 롤백 (HEAD~1)", "callback_data": "rollback_head"},
                {"text": "🔍 상태 대시보드 확인", "url": GRAFANA_URL}
            ]]
        }
    send_telegram_message(text, reply_markup)
    return {"status": "ok", "alerts_processed": len(alerts)}

@app.post("/webhook/finops")
async def finops_webhook(req: Optional[CustomRollbackRequest] = None):
    """2️⃣ FinOps OOMKill 위험 및 지정 버전 롤백 알림"""
    if req is None:
        req = CustomRollbackRequest()
        
    target_tag = req.target_tag if req.target_tag else "v1.0.0"
    text = (
        "⚠️ *[FinOps 엔진 분석]*\n"
        "Memory 사용량이 p99 한계치에 다다랐습니다. (OOMKill 위험)\n"
        f"안정성을 위해 지정 버전(`{target_tag}`)으로 롤백을 추천합니다."
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"⏪ 지정 버전({target_tag}) 롤백 실행", "callback_data": f"rollback_custom_{target_tag}"}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

@app.post("/webhook/deploy-request")
async def deploy_request_webhook(req: Optional[DeployRequest] = None):
    """3️⃣ KRR 최적화 스펙 승인 요청 알림"""
    if req is None:
        req = DeployRequest()

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

@app.post("/webhook/rollout")
async def rollout_failed_webhook(request: Request):
    """4️⃣ Argo Rollouts 검증 실패 및 자동 롤백 알림"""
    try:
        data = await request.json()
        rollout_name = data.get("rollout", "mak-app")
        reason = data.get("reason", "AnalysisRun Metrics 검증 실패 (Success Rate / Latency 임계치 초과)")
    except Exception:
        rollout_name = "mak-app"
        reason = "AnalysisRun Metrics 검증 실패 (Success Rate / Latency 임계치 초과)"

    text = (
        "❌ *[Argo Rollouts 검증 실패 알림]*\n"
        f"• **Target Rollout**: `{rollout_name}`\n"
        f"• **사유**: {reason}\n\n"
        "⚠️ 카나리 검증 단계에서 이상이 감지되어 **자동 롤백**되었습니다.\n"
        "이전 커밋 버전 상태 및 Pod 로그를 점검하세요."
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": "🔍 Grafana 대시보드", "url": GRAFANA_URL}
        ]]
    }
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

@app.post("/webhook/telegram")
async def telegram_callback_webhook(request: Request):
    """5️⃣ 텔레그램 버튼 클릭(Callback) 처리"""
    data = await request.json()
    
    if "callback_query" in data:
        callback = data["callback_query"]
        callback_data = callback.get("data", "")
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        
        if callback_data == "rollback_head":
            update_telegram_message(chat_id, message_id, "⏳ *[롤백 진행 중]* 직전 커밋 버전으로 롤백 파이프라인을 실행합니다...")
            trigger_github_workflow("rollback.yaml")
            update_telegram_message(chat_id, message_id, "✅ *[롤백 완료]* 직전 커밋 버전 롤백 파이프라인이 성공적으로 호출되었습니다!")

        elif callback_data.startswith("rollback_custom_"):
            target_tag = callback_data.replace("rollback_custom_", "")
            update_telegram_message(chat_id, message_id, f"⏳ *[지정 롤백 진행 중]* `{target_tag}` 버전으로 롤백 중입니다...")
            trigger_github_workflow("rollback-custom.yaml", {"target_tag": target_tag})
            update_telegram_message(chat_id, message_id, f"✅ *[지정 롤백 완료]* `{target_tag}` 버전 롤백 파이프라인이 실행되었습니다!")

        elif callback_data.startswith("deploy_approve_"):
            target_tag = callback_data.replace("deploy_approve_", "")
            update_telegram_message(chat_id, message_id, f"⏳ *[배포 진행 중]* `{target_tag}` 버전 최적화 배포를 시작합니다...")
            trigger_github_workflow("deploy.yaml", {"target_tag": target_tag})
            update_telegram_message(chat_id, message_id, f"🚀 *[배포 승인 완료]* `{target_tag}` 최적화 배포 파이프라인이 성공적으로 가동되었습니다!")

    return {"status": "ok"}