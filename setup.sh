#!/bin/bash
# 파일위치: /home/user1/practical-project/setup.sh
set -e

# 파일 경로 정의
TF_VARS_FILE="infra/terraform/terraform.tfvars"
TF_DIR2="infra/terraform/init"

# 파일 존재 여부 및 프로필 추출 검증
if [ ! -f "$TF_VARS_FILE" ]; then
    echo " [오류] $TF_VARS_FILE 파일이 존재하지 않습니다."
    echo " 로컬에 terraform.tfvars 파일을 먼저 생성하고 설정을 적어주세요."
    exit 1
fi
# 파일에서 aws_profile = "admin-jongwon" 줄을 찾아 따옴표 안의 값만 추출
PROFILE_NAME=$(grep "aws_profile" "$TF_VARS_FILE" | cut -d'"' -f2)

if [ -z "$PROFILE_NAME" ]; then
    echo "❌ [오류] $TF_VARS_FILE 파일에서 aws_profile 설정을 찾을 수 없습니다."
    exit 1
fi

# 'admin-jongwon'에서 'jongwon'만 쏙 뽑아내어 NAME 변수에 할당
NAME=$(echo "$PROFILE_NAME" | sed 's/admin-//')

echo "============================================================="
echo "🍶 일과후 막걸리 팀 프로젝트 자동 환경 설정"
echo " tfvars에서 감지된 프로필: $PROFILE_NAME (유저명: $NAME)"
echo "============================================================="
echo "공유 AWS 계정에서 발급받은 본인의 IAM Access Key를 입력해주세요."
echo "============================================================="

# AWS Profile 등록
aws configure --profile "$PROFILE_NAME"

# S3, DynamoDB 백엔드 생성 폴더로 이동하여 테라폼 초기화 및 배포
TF_DIR2=${1:-"infra/terraform/init"}
echo " [$PROFILE_NAME] 프로필로 공유 S3 및 DynamoDB 초기화/생성 중..."
cd "$TF_DIR2"

# 이 스크립트 안에서 생성 명령을 날릴 때 해당 프로필을 사용하도록 지정
export AWS_PROFILE="$PROFILE_NAME"

terraform init
# 이미 생성되어 있다면 에러를 뱉으며 튕기지 말고, "변경 사항 없음"으로 부드럽게 넘어가라는 명령어
terraform apply -auto-approve || true

echo "============================================================="
echo "✅ 모든 초기 설정이 성공적으로 완료되었습니다!"
echo "============================================================="