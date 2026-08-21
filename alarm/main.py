import os
import requests
import threading
import time
import base64
from typing import Optional
from fastapi import FastAPI, Request, UploadFile, File, Form
from pydantic import BaseModel
from dotenv import load_dotenv

# ==========================================
# ⚙️ 1. 환경 변수 세팅 (.env 상위/현재 자동 탐색)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_alarm = os.path.join(BASE_DIR, ".env")
env_root = os.path.join(os.path.dirname(BASE_DIR), ".env")

# alarm/.env 가 없으면 최상위 .env 자동 로드 (K8s Secret 우선 보호)
if os.path.exists(env_alarm):
    load_dotenv(env_alarm, override=False)
elif os.path.exists(env_root):
    load_dotenv(env_root, override=False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_UPDATE_MODE = os.getenv("TELEGRAM_UPDATE_MODE", "webhook").lower()
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "https://alarm.tuby.shop").rstrip("/")

# --------------------------------------------------
# 🔑 GITHUB_TOKEN 로드 및 Base64 자동 디코딩 방어 로직
# --------------------------------------------------
raw_token = os.getenv("GITOPS_TOKEN", "")

# 'Z2hv'로 시작하면 Base64 인코딩된 'ghp_' 토큰이므로 자동 디코딩
if raw_token and raw_token.startswith("Z2hv"):
    try:
        GITHUB_TOKEN = base64.b64decode(raw_token).decode("utf-8")
        print("💡 [INFO] Base64로 인코딩된 GITOPS_TOKEN을 원문(ghp_...)으로 복원했습니다.")
    except Exception:
        GITHUB_TOKEN = raw_token
else:
    GITHUB_TOKEN = raw_token

GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "After-mak")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "mak-argocd-deploy")
TARGET_BRANCH = os.getenv("TARGET_BRANCH", "main")
ROLLBACK_WORKFLOW_REPO_NAME = os.getenv("ROLLBACK_WORKFLOW_REPO_NAME", "practical-project")
ROLLBACK_WORKFLOW_BRANCH = os.getenv("ROLLBACK_WORKFLOW_BRANCH", "dev")
GITOPS_TARGET_BRANCH = os.getenv("GITOPS_TARGET_BRANCH", "main")

# 상우 님 FinOps(KRR) 정책 분석 엔진 서비스 주소 (ClusterIP)
FINOPS_URL = os.getenv("FINOPS_URL", "http://finops-analyzer-service.default.svc.cluster.local:8000")

GRAFANA_URL = "https://grafana.tuby.shop/login"

# 🔍 .env 로딩 여부 및 토큰 상태 점검 로그
print("--------------------------------------------------")
print(f"🔑 TELEGRAM_BOT_TOKEN 로드 상태: {'✅ 성공' if TELEGRAM_BOT_TOKEN else '❌ 실패 (None)'}")
print(f"🆔 TELEGRAM_CHAT_ID 로드 상태: {'✅ 성공' if TELEGRAM_CHAT_ID else '❌ 실패 (None)'}")
if GITHUB_TOKEN:
    print(f"🔑 GITHUB_TOKEN 로드 상태: ✅ 성공 (시작문자: {GITHUB_TOKEN[:4]}***)")
else:
    print("❌ GITHUB_TOKEN 로드 상태: ❌ 실패 (None)")
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
        "parse_mode": "HTML"
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

def send_telegram_document(filename: str, content: bytes, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    files = {"document": (filename, content, "text/plain")}
    data = {"chat_id": TELEGRAM_CHAT_ID}
    if caption:
        data["caption"] = caption
    try:
        res = requests.post(url, data=data, files=files, timeout=30)
        print(f"📎 Telegram 파일 전송 결과 -> 응답 코드: {res.status_code}")
        if res.status_code != 200:
            print(f"❌ Telegram 파일 전송 실패 상세: {res.text}")
            return False
        return True
    except Exception as e:
        print(f"❌ Telegram 파일 전송 에러: {e}")
        return False

def update_telegram_message(chat_id: int, message_id: int, new_text: str, parse_mode: str = "HTML"):
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

# 상우 님 FinOps 분석 엔진에서 동적 권장 리소스(final_cpu, final_memory) 조회
def fetch_finops_recommendation(namespace: str, deployment_name: str, container_name: str) -> Optional[dict]:
    try:
        url = f"{FINOPS_URL}/recommendation/{namespace}/{deployment_name}"
        res = requests.get(url, params={"container_name": container_name}, timeout=10)
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
        # inputs 값을 강제로 문자열(str)로 변환 (GitHub API 422 에러 방지)
        payload["inputs"] = {str(k): str(v) for k, v in inputs.items()}
        
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"📡 GitHub API [{workflow_file}] 호출 완료 -> 응답 코드: {res.status_code}")
        
        if res.status_code not in [200, 201, 202, 204]:
            error_detail = res.text
            print(f"❌ GitHub API 에러 상세: {error_detail}")
            send_telegram_message(
                f"🚨 <b>[GitHub Actions 호출 실패]</b>\n"
                f"• Repository: <code>{GITHUB_REPO_OWNER}/{target_repo}</code>\n"
                f"• Workflow: <code>{workflow_file}</code>\n"
                f"• HTTP 상태코드: <code>{res.status_code}</code>\n"
                f"• 상세 원인: <code>{error_detail}</code>"
            )
            return False
        return True
    except Exception as e:
        print(f"❌ GitHub API 호출 에러: {e}")
        send_telegram_message(f"🚨 <b>[GitHub API 통신 에러]</b>: <code>{e}</code>")
        return False

# ==========================================
# 📩 Webhook Endpoints
# ==========================================

# 1. Alertmanager 수신
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
        lines.append(f"{icon} <b>{alertname}</b> ({severity}) - {status}\n{summary}")
        if status == "firing":
            any_firing = True

    text = "<b>[Alertmanager 장애 알림]</b>\n\n" + "\n\n".join(lines)
    reply_markup = None
    if any_firing:
        text += "\n\n최근 배포로 인한 영향일 수 있습니다. 이전 버전으로 롤백하시겠습니까?"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "⏪ 직전 버전 롤백 (HEAD~1)", "callback_data": "rollback_head"},
                {"text": "🔍 Grafana 대시보드", "url": GRAFANA_URL}
            ]]
        }
    send_telegram_message(text, reply_markup)
    return {"status": "ok", "alerts_processed": len(alerts)}

# 2. 상우 님 FinOps 분석 리포트 수신 연동 (★ 핵심 통합 포인트)
@app.post("/webhook/deploy-request")
async def handle_finops_report(payload: dict):
    deployment_name = payload.get("deployment_name", payload.get("deployment", "sample-worker"))
    namespace = payload.get("namespace", "sample-fastapi")
    telegram_message = payload.get("telegram_message", "")
    overall_status = payload.get("overall_status", "PASS")
    
    reply_markup = None
    # 상우 님 엔진의 8종 안전 정책을 통과(PASS)한 경우 인라인 승인/거부 버튼 첨부
    if overall_status == "PASS":
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ 승인 (Apply)", "callback_data": f"infra_approve:{namespace}:{deployment_name}"},
                {"text": "❌ 거부 (Reject)", "callback_data": f"infra_reject:{namespace}:{deployment_name}"}
            ]]
        }
    
    # 상우 님이 생성한 HTML/마크다운 텍스트 보고서(표)를 그대로 전달
    msg_text = telegram_message if telegram_message else f"💡 <b>[FinOps 추천]</b> {namespace}/{deployment_name}"
    send_telegram_message(msg_text, reply_markup=reply_markup)
    return {"status": "ok", "message": "FinOps report sent to Telegram"}

# 2-1. 전체 워크로드 상세 리포트 파일 수신 (승인/거절 메시지보다 먼저 도착해서 따로 열어볼 수 있음)
@app.post("/webhook/deploy-batch-report")
async def handle_deploy_batch_report(file: UploadFile = File(...), caption: str = Form("")):
    content = await file.read()
    ok = send_telegram_document(file.filename, content, caption)
    return {"status": "ok" if ok else "error"}

# 2-2. 전체 워크로드를 하나의 메시지로 묶은 승인/거절 카드 (워크로드마다 버튼 한 줄씩)
@app.post("/webhook/deploy-batch-approval")
async def handle_deploy_batch_approval(payload: dict):
    workloads = payload.get("workloads", [])
    if not workloads:
        return {"status": "ignored", "reason": "no workloads in payload"}

    lines = []
    keyboard_rows = []
    for w in workloads:
        namespace = w.get("namespace", "")
        deployment_name = w.get("deployment_name", "")
        container_name = w.get("container_name", "")
        overall_status = w.get("overall_status", "PASS")
        line = w.get("line") or f"{namespace}/{deployment_name}/{container_name}"
        lines.append(line)

        if overall_status == "PASS" and namespace and deployment_name and container_name:
            keyboard_rows.append([
                {"text": f"✅ 승인 {deployment_name}/{container_name}", "callback_data": f"infra_approve:{namespace}:{deployment_name}:{container_name}"},
                {"text": f"❌ 거부 {deployment_name}/{container_name}", "callback_data": f"infra_reject:{namespace}:{deployment_name}:{container_name}"}
            ])

    text = f"💡 <b>[FinOps 최적화 권장안]</b> ({len(workloads)}개 워크로드)\n\n" + "\n\n".join(lines)
    reply_markup = {"inline_keyboard": keyboard_rows} if keyboard_rows else None
    send_telegram_message(text, reply_markup=reply_markup)
    return {"status": "ok", "message": "Batch approval message sent to Telegram"}

# 3. KEDA 오토스케일링 수신
@app.post("/webhook/keda-scale")
async def keda_scale_webhook(request: Request):
    try:
        data = await request.json()
        scaled_object = data.get("scaledObject", data.get("scaledobject", "finops-tg-scaler"))
        namespace = data.get("namespace", "default")
        replicas = data.get("replicas", "unknown")
    except Exception:
        scaled_object = "finops-tg-scaler"
        namespace = "default"
        replicas = "여러 개"

    text = (
        "📈 <b>[KEDA 오토스케일링 감지 알림]</b>\n\n"
        f"• <b>ScaledObject</b>: <code>{scaled_object}</code>\n"
        f"• <b>Namespace</b>: <code>{namespace}</code>\n"
        f"• <b>현재 확장된 파드 수</b>: <code>{replicas}</code>개\n\n"
        "⚡ 트래픽/대기열 부하가 감지되어 KEDA가 파드를 자동 확장했습니다!"
    )
    send_telegram_message(text)
    return {"status": "ok"}

# 4. Argo Rollouts 수신
@app.post("/webhook/rollout")
async def rollout_failed_webhook(request: Request):
    try:
        data = await request.json()
        rollout_name = data.get("rollout", "mak-app")
        reason = data.get("reason", "AnalysisRun Metrics 임계치 초과")
    except Exception:
        rollout_name = "mak-app"
        reason = "AnalysisRun Metrics 임계치 초과"

    text = (
        "❌ <b>[Argo Rollouts 검증 실패 알림]</b>\n\n"
        f"• <b>Target Rollout</b>: <code>{rollout_name}</code>\n"
        f"• <b>사유</b>: {reason}\n\n"
        "⚠️ 카나리 검증 실패로 <b>자동 롤백</b>되었습니다."
    )
    reply_markup = {"inline_keyboard": [[{"text": "🔍 Grafana 대시보드", "url": GRAFANA_URL}]]}
    send_telegram_message(text, reply_markup)
    return {"status": "ok"}

# 5. 텔레그램 인라인 버튼 콜백 수신 핸들러 (상우 님 엔진 동적 재조회 연동)
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
        
        # 1) 직전 버전 롤백
        if callback_data == "rollback_head":
            update_telegram_message(chat_id, message_id, "⏳ <b>[롤백 진행 중]</b> 직전 커밋 버전 롤백 파이프라인을 실행합니다...")
            started = trigger_github_workflow(
                "rollback.yaml",
                {"target_branch": GITOPS_TARGET_BRANCH},
                repo_name=ROLLBACK_WORKFLOW_REPO_NAME,
                ref=ROLLBACK_WORKFLOW_BRANCH,
            )
            if started:
                update_telegram_message(chat_id, message_id, "✅ <b>[롤백 요청 완료]</b> 직전 커밋 버전 롤백 파이프라인이 시작되었습니다!")
            else:
                update_telegram_message(chat_id, message_id, "❌ <b>[롤백 요청 실패]</b> GitHub Actions 파이프라인을 시작하지 못했습니다.")

        # 2) Custom 태그 지정 롤백
        elif callback_data.startswith("rollback_custom_"):
            target_tag = callback_data.replace("rollback_custom_", "")
            update_telegram_message(chat_id, message_id, f"⏳ <b>[지정 롤백 진행 중]</b> <code>{target_tag}</code> 버전 롤백 중...")
            started = trigger_github_workflow(
                "rollback-custom.yaml",
                {"target_tag": target_tag, "target_branch": GITOPS_TARGET_BRANCH},
                repo_name=ROLLBACK_WORKFLOW_REPO_NAME,
                ref=ROLLBACK_WORKFLOW_BRANCH,
            )
            if started:
                update_telegram_message(chat_id, message_id, f"✅ <b>[지정 롤백 요청 완료]</b> <code>{target_tag}</code> 버전 롤백 파이프라인이 시작되었습니다!")
            else:
                update_telegram_message(chat_id, message_id, f"❌ <b>[지정 롤백 요청 실패]</b> <code>{target_tag}</code> 롤백 파이프라인을 시작하지 못했습니다.")

        # 4) FinOps 권장안 거부
        elif callback_data == "infra_reject" or callback_data.startswith("infra_reject:"):
            rest = callback_data[len("infra_reject"):].lstrip(":")
            parts = rest.split(":", 2)
            target_namespace = parts[0] if len(parts) > 0 else ""
            target_deployment = parts[1] if len(parts) > 1 else ""
            target_container = parts[2] if len(parts) > 2 else ""
            label = f"{target_namespace}/{target_deployment}/{target_container}" if target_deployment and target_container else "대상 워크로드"
            update_telegram_message(
                chat_id, message_id,
                append_progress_status(
                    original_text,
                    f"❌ <b>[거부 완료]</b> <code>{label}</code> 최적화 권장안을 거부했습니다. 현재 설정을 유지합니다."
                )
            )

        # 3) FinOps 최적화 권장안 승인 (상우 님 엔진 동적 재조회 후 GitHub Actions 반영)
        elif callback_data == "infra_approve" or callback_data.startswith("infra_approve:"):
            rest = callback_data[len("infra_approve"):].lstrip(":")
            parts = rest.split(":", 2)
            target_namespace = parts[0] if len(parts) > 0 else ""
            target_deployment = parts[1] if len(parts) > 1 else ""
            target_container = parts[2] if len(parts) > 2 else ""

            if not target_namespace or not target_deployment or not target_container:
                update_telegram_message(
                    chat_id, message_id,
                    append_progress_status(
                        original_text,
                        "⚠️ <b>[적용 실패]</b> 콜백 데이터에 namespace/deployment/container 정보가 없어 어떤 워크로드에 적용할지 알 수 없습니다."
                    ),
                    parse_mode="HTML"
                )
            else:
                label = f"{target_namespace}/{target_deployment}/{target_container}"
                update_telegram_message(
                    chat_id, message_id,
                    append_progress_status(original_text, f"⏳ <b>[적용 준비 중]</b> <code>{label}</code>의 최신 권장값을 FinOps 엔진에서 조회하는 중입니다..."),
                    parse_mode="HTML"
                )

                recommendation = fetch_finops_recommendation(target_namespace, target_deployment, target_container)
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
                            "container_name": target_container,
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