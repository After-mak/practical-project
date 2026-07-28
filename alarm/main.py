import os
import requests
import threading
import time
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
TELEGRAM_UPDATE_MODE = os.getenv("TELEGRAM_UPDATE_MODE", "webhook").lower()
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "https://alarm.tuby.shop").rstrip("/")

GITHUB_TOKEN = os.getenv("GITOPS_TOKEN")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "After-mak")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "mak-argocd-deploy")
# ✅ 수정 1: mak-argocd-deploy의 기본 브랜치는 main이므로 기본값을 main으로 변경
TARGET_BRANCH = os.getenv("TARGET_BRANCH", "main")
ROLLBACK_WORKFLOW_REPO_NAME = os.getenv("ROLLBACK_WORKFLOW_REPO_NAME", "practical-project")
ROLLBACK_WORKFLOW_BRANCH = os.getenv("ROLLBACK_WORKFLOW_BRANCH", "dev")
GITOPS_TARGET_BRANCH = os.getenv("GITOPS_TARGET_BRANCH", "main")

# FinOps(KRR) 정책 엔진 서비스 주소. 
FINOPS_URL = os.getenv("FINOPS_URL", "http://finops-analyzer.finops.svc.cluster.local:8000")

GRAFANA_URL = "http://tuby.shop:3000"

# 🔍 .env 로딩 여부 터미널 점검 로그
print("--------------------------------------------------")
print(f"🔑 TELEGRAM_BOT_TOKEN 로드 상태: {'✅ 성공' if TELEGRAM_BOT_TOKEN else '❌ 실패 (None)'}")
print(f"🆔 TELEGRAM_CHAT_ID 로드 상태: {'✅ 성공' if TELEGRAM_CHAT_ID else '❌ 실패 (None)'}")
print("--------------------------------------------------")

app = FastAPI(title="FinOps Telegram Alert Gateway")

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "tg-gateway"}


def poll_telegram_updates():
    """공개 인바운드 경로가 없어도 Telegram callback_query를 수신합니다."""
    offset = 0
    time.sleep(1)
    while True:
        try:
            res = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": '["callback_query"]'},
                timeout=30,
            )
            payload = res.json()
            if not payload.get("ok"):
                print(f"⚠️ Telegram polling 실패: {payload}")
                time.sleep(5)
                continue

            for update in payload.get("result", []):
                callback_res = requests.post(
                    "http://127.0.0.1:8000/webhook/telegram",
                    json=update,
                    timeout=30,
                )
                callback_res.raise_for_status()
                offset = update["update_id"] + 1
        except Exception as e:
            print(f"❌ Telegram polling 에러: {e}")
            time.sleep(5)


@app.on_event("startup")
def configure_telegram_updates():
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN이 없어 callback 수신 설정을 건너뜁니다.")
        return

    if TELEGRAM_UPDATE_MODE == "polling":
        res = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=10,
        )
        res.raise_for_status()
        threading.Thread(target=poll_telegram_updates, daemon=True).start()
        print("✅ Telegram callback 수신 모드: polling")
        return

    if TELEGRAM_UPDATE_MODE == "webhook":
        if not TELEGRAM_WEBHOOK_URL:
            raise RuntimeError("TELEGRAM_UPDATE_MODE=webhook이면 TELEGRAM_WEBHOOK_URL이 필요합니다.")
        res = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={
                "url": f"{TELEGRAM_WEBHOOK_URL}/webhook/telegram",
                "allowed_updates": ["callback_query"],
            },
            timeout=10,
        )
        res.raise_for_status()
        print(f"✅ Telegram callback 수신 모드: webhook ({TELEGRAM_WEBHOOK_URL}/webhook/telegram)")
        return

    raise RuntimeError("TELEGRAM_UPDATE_MODE는 polling 또는 webhook이어야 합니다.")

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

def update_telegram_message(chat_id: int, message_id: int, new_text: str, parse_mode: str = "Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": parse_mode
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200 and res.json().get("ok"):
            return
        print(f"⚠️ Telegram 메시지 수정 실패({parse_mode}) -> {res.status_code}: {res.text}. plain-text로 재시도합니다.")
        payload.pop("parse_mode", None)
        fallback_res = requests.post(url, json=payload, timeout=5)
        if not (fallback_res.status_code == 200 and fallback_res.json().get("ok")):
            print(f"❌ Telegram 메시지 수정 plain-text 재시도도 실패 -> {fallback_res.status_code}: {fallback_res.text}")
    except Exception as e:
        print(f"❌ Telegram 메시지 수정 에러: {e}")


def answer_telegram_callback(callback_query_id: str, text: str = "요청을 접수했습니다."):
    if not callback_query_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=5,
        )
    except Exception as e:
        print(f"❌ Telegram callback 응답 에러: {e}")

def append_progress_status(original_text: str, status_line: str) -> str:
    if original_text:
        return f"{original_text}\n\n{status_line}"
    return status_line

def fetch_finops_recommendation(namespace: str, deployment_name: str) -> Optional[dict]:
    try:
        url = f"{FINOPS_URL}/recommendation/{namespace}/{deployment_name}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
        print(f"⚠️ FinOps 추천값 조회 실패 -> 응답 코드: {res.status_code}, 내용: {res.text[:300]}")
        return None
    except Exception as e:
        print(f"❌ FinOps 추천값 조회 에러: {e}")
        return None

def trigger_github_workflow(
    workflow_file: str,
    inputs: dict = None,
    repo_name: str = None,
    ref: str = None,
) -> bool:
    target_repo = repo_name or GITHUB_REPO_NAME
    target_ref = ref or TARGET_BRANCH
    url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{target_repo}/actions/workflows/{workflow_file}/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": target_ref}
    if inputs:
        # ✅ 수정 2: 모든 inputs 값을 강제로 문자열(str)로 변환 (422 타입 에러 방지)
        payload["inputs"] = {str(k): str(v) for k, v in inputs.items()}
        
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"📡 GitHub API [{workflow_file}] 호출 완료 -> 응답 코드: {res.status_code}")
        
        if res.status_code not in [200, 201, 202, 204]:
            # ✅ 수정 3: 실패 상세 사유 출력 및 텔레그램 알림 포함
            error_detail = res.text
            print(f"❌ GitHub API 에러 상세: {error_detail}")
            
            send_telegram_message(
                f"🚨 *[GitHub Actions 호출 실패]*\n"
                f"• Repository: `{GITHUB_REPO_OWNER}/{target_repo}`\n"
                f"• Workflow: `{workflow_file}`\n"
                f"• HTTP 상태코드: `{res.status_code}`\n"
                f"• 상세 원인: `{error_detail}`\n"
                f"• 토큰/권한 및 `.env` 설정을 확인하세요."
            )
            return False
        return True
    except Exception as e:
        print(f"❌ GitHub API 호출 에러: {e}")
        send_telegram_message(f"🚨 *[GitHub API 통신 에러]*: `{e}`")
        return False

# ==========================================
# 📩 Webhook Endpoints (총 5개)
# ==========================================
@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request):
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
    data = await request.json()
    
    if "callback_query" in data:
        callback = data["callback_query"]
        answer_telegram_callback(callback.get("id", ""))
        callback_data = callback.get("data", "")
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        original_text = callback["message"].get("text", "")
        
        if callback_data == "rollback_head":
            update_telegram_message(chat_id, message_id, "⏳ *[롤백 진행 중]* 직전 커밋 버전으로 롤백 파이프라인을 실행합니다...")
            started = trigger_github_workflow(
                "rollback.yaml",
                {"target_branch": GITOPS_TARGET_BRANCH},
                repo_name=ROLLBACK_WORKFLOW_REPO_NAME,
                ref=ROLLBACK_WORKFLOW_BRANCH,
            )
            if started:
                update_telegram_message(chat_id, message_id, "✅ *[롤백 요청 완료]* 직전 커밋 버전 롤백 파이프라인이 시작되었습니다!")
            else:
                update_telegram_message(chat_id, message_id, "❌ *[롤백 요청 실패]* GitHub Actions 파이프라인을 시작하지 못했습니다.")

        elif callback_data.startswith("rollback_custom_"):
            target_tag = callback_data.replace("rollback_custom_", "")
            update_telegram_message(chat_id, message_id, f"⏳ *[지정 롤백 진행 중]* `{target_tag}` 버전으로 롤백 중입니다...")
            started = trigger_github_workflow(
                "rollback-custom.yaml",
                {"target_tag": target_tag, "target_branch": GITOPS_TARGET_BRANCH},
                repo_name=ROLLBACK_WORKFLOW_REPO_NAME,
                ref=ROLLBACK_WORKFLOW_BRANCH,
            )
            if started:
                update_telegram_message(chat_id, message_id, f"✅ *[지정 롤백 요청 완료]* `{target_tag}` 버전 롤백 파이프라인이 시작되었습니다!")
            else:
                update_telegram_message(chat_id, message_id, f"❌ *[지정 롤백 요청 실패]* `{target_tag}` 롤백 파이프라인을 시작하지 못했습니다.")

        elif callback_data.startswith("deploy_approve_"):
            target_tag = callback_data.replace("deploy_approve_", "")
            update_telegram_message(chat_id, message_id, f"⏳ *[배포 진행 중]* `{target_tag}` 버전 최적화 배포를 시작합니다...")
            
            # ✅ 수정 4: deploy.yaml 호출 시 GITOPS_TARGET_BRANCH (main) 강제 지정
            trigger_github_workflow(
                "deploy.yaml", 
                {"target_tag": target_tag},
                ref=GITOPS_TARGET_BRANCH
            )
            update_telegram_message(chat_id, message_id, f"🚀 *[배포 승인 완료]* `{target_tag}` 최적화 배포 파이프라인이 성공적으로 가동되었습니다!")

        elif callback_data == "infra_reject" or callback_data.startswith("infra_reject:"):
            rest = callback_data[len("infra_reject"):].lstrip(":")
            target_namespace, _, target_deployment = rest.partition(":")
            label = f"{target_namespace}/{target_deployment}" if target_deployment else "대상 워크로드"
            update_telegram_message(
                chat_id, message_id,
                append_progress_status(
                    original_text,
                    f"❌ <b>[반려 완료]</b> <code>{label}</code> 리소스 최적화 권장안을 반려했습니다. 현재 리소스 설정을 그대로 유지합니다."
                ),
                parse_mode="HTML"
            )

        elif callback_data == "infra_approve" or callback_data.startswith("infra_approve:"):
            rest = callback_data[len("infra_approve"):].lstrip(":")
            target_namespace, _, target_deployment = rest.partition(":")

            if not target_namespace or not target_deployment:
                update_telegram_message(
                    chat_id, message_id,
                    append_progress_status(
                        original_text,
                        "⚠️ <b>[적용 실패]</b> 콜백 데이터에 namespace/deployment 정보가 없어 어떤 워크로드에 적용할지 알 수 없습니다."
                    ),
                    parse_mode="HTML"
                )
            else:
                label = f"{target_namespace}/{target_deployment}"
                update_telegram_message(
                    chat_id, message_id,
                    append_progress_status(original_text, f"⏳ <b>[적용 준비 중]</b> <code>{label}</code>의 최신 권장값을 FinOps 엔진에서 조회하는 중입니다..."),
                    parse_mode="HTML"
                )

                recommendation = fetch_finops_recommendation(target_namespace, target_deployment)
                if recommendation is None:
                    update_telegram_message(
                        chat_id, message_id,
                        append_progress_status(
                            original_text,
                            f"⚠️ <b>[적용 실패]</b> <code>{label}</code>의 최근 분석 결과를 찾을 수 없습니다 (만료되었거나 FinOps 엔진 연결 실패). "
                            f"FinOps에서 분석을 다시 실행한 뒤 승인해주세요."
                        ),
                        parse_mode="HTML"
                    )
                else:
                    final_cpu = recommendation["final_cpu"]
                    final_memory = recommendation["final_memory"]
                    update_telegram_message(
                        chat_id, message_id,
                        append_progress_status(
                            original_text,
                            f"⏳ <b>[적용 진행 중]</b> <code>{label}</code>에 CPU <code>{final_cpu}</code> / Memory <code>{final_memory}</code> 반영을 시작합니다..."
                        ),
                        parse_mode="HTML"
                    )

                    # ✅ 수정 5: finops-apply.yaml 호출 시에도 GITOPS_TARGET_BRANCH (main) 강제 지정
                    trigger_github_workflow(
                        "finops-apply.yaml",
                        {
                            "namespace": target_namespace,
                            "deployment_name": target_deployment,
                            "cpu": final_cpu,
                            "memory": final_memory,
                        },
                        ref=GITOPS_TARGET_BRANCH
                    )
                    update_telegram_message(
                        chat_id, message_id,
                        append_progress_status(
                            original_text,
                            f"✅ <b>[적용 요청 완료]</b> <code>{label}</code>에 CPU <code>{final_cpu}</code> / Memory <code>{final_memory}</code> 반영 파이프라인이 시작되었습니다!"
                        ),
                        parse_mode="HTML"
                    )

    return {"status": "ok"}