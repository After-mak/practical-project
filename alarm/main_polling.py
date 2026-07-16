#무적의 임시 테스트용 파이썬 코드(Polling 방식)
import time
import requests

# .env 파일에서 토큰 가져오기
with open(".env", "r") as f:
    for line in f:
        if "TELEGRAM_BOT_TOKEN" in line:
            TOKEN = line.split("=")[1].strip().replace('"', '')

print("🟢 [김민규 모듈] 폴링(Polling) 방식으로 승인 대기 중...")
last_update_id = 0

while True:
    try:
        # 텔레그램 본사 서버에 새로운 버튼 입력이 들어왔는지 수신 (GetUpdates)
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
        res = requests.get(url).json()
        
        if res.get("ok") and res.get("result"):
            for update in res["result"]:
                last_update_id = update["update_id"]
                
                # 버튼(Callback Query) 클릭 감지
                if "callback_query" in update:
                    data = update["callback_query"]["data"]
                    if data == "infra_approve":
                        print("\n🟢  텔레그램 승인 확인 완료!")
                        print("🚀  변경된 인프라 설정을 공용 레포지토리에 반영 중 (Git Push)...")
                        print("🟢 GitOps 레포지토리 업데이트 완료 -> Argo CD가 이를 감지하여 자동 동기화할 예정입니다.\n")
                    elif data == "infra_reject":
                        print("\n🔴  승인이 거부되었습니다.\n")
                        
    except Exception as e:
        print(f"에러 발생: {e}")
    time.sleep(1)
