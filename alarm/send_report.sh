#!/bin/bash
#/home/user1/practical-project/alarm/send_report.sh

# 1. 쉘 스크립트가 위치한 경로를 기준점으로 설정
BASE_DIR="/home/user1/practical-project"
CD_ENVS="$BASE_DIR/.env"

# 2. .env 파일에서 텔레그램 토큰 정보 파싱
if [ -f "$CD_ENVS" ]; then
    TOKEN=$(grep TELEGRAM_BOT_TOKEN "$CD_ENVS" | cut -d'=' -f2 | tr -d '"' | tr -d '\r')
else
    echo "❌ .env 파일을 찾을 수 없습니다."
    exit 1
fi

# 3. 사용자 정보 세팅 (민규 님의 Chat ID)
CHAT_ID="8400631912"

# 🎯 [수정 완료] BASE_DIR(루트 폴더)에 있는 finops_report.md를 정확하게 가리킵니다.
REPORT_FILE="$BASE_DIR/finops_report.md"

# 4. 리포트 파일 존재 여부 확인 후 내용 읽기
if [ -f "$REPORT_FILE" ]; then
    REPORT_TEXT=$(cat "$REPORT_FILE")
else
    echo "❌ 리포트 파일이 존재하지 않습니다: $REPORT_FILE"
    exit 1
fi

# 5. 텔레그램 전송 시 공백이나 특수문자가 깨지지 않도록 URL 인코딩 처리
ENCODED_TEXT=$(echo "$REPORT_TEXT" | jq -sRr @uri)

# 6. 인라인 키보드(승인/거부 버튼) 구조 정의
KEYBOARD='{"inline_keyboard": [[
    {"text": "✅ 승인 (Apply)", "callback_data": "infra_approve"},
    {"text": "❌ 거부 (Reject)", "callback_data": "infra_reject"}
]]}'
ENCODED_KEYBOARD=$(echo "$KEYBOARD" | jq -sRr @uri)

# 7. 텔레그램 API 호출하여 메시지 발송
RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage?chat_id=$CHAT_ID&text=$ENCODED_TEXT&reply_markup=$ENCODED_KEYBOARD")

# 8. 발송 결과 확인
if echo "$RESPONSE" | grep -q '"ok":true'; then
    echo "🚀  텔레그램 FinOps 리포트 및 승인 요청 전송 완료!"
else
    echo "❌ 텔레그램 전송 실패: $RESPONSE"
fi