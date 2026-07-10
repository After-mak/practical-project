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

# 대화형 창을 없애고 스크립트 안에서 안전하게 키를 입력받습니다.
read -p "🔑 AWS Access Key ID: " USER_ACCESS_KEY
read -p "🔒 AWS Secret Access Key: " USER_SECRET_KEY

if [ -z "$USER_ACCESS_KEY" ] || [ -z "$USER_SECRET_KEY" ]; then
    echo "❌ [오류] 키 값이 입력되지 않았습니다. 설정을 중단합니다."
    exit 1
fi

# default를 절대 건드리지 않고, 지정된 프로필명으로만 키를 강제 주입합니다.
aws configure set aws_access_key_id "$USER_ACCESS_KEY" --profile "$PROFILE_NAME"
aws configure set aws_secret_access_key "$USER_SECRET_KEY" --profile "$PROFILE_NAME"
aws configure set region "ap-northeast-2" --profile "$PROFILE_NAME"
aws configure set output "json" --profile "$PROFILE_NAME"

# =============================================================
# S3, DynamoDB 백엔드 생성 폴더로 이동하여 테라폼 초기화 및 배포
# =============================================================
echo " [$PROFILE_NAME] 프로필로 공유 S3 및 DynamoDB 초기화/생성 중..."
cd "$TF_DIR2"

# 이 스크립트 안에서 생성 명령을 날릴 때 해당 프로필을 사용하도록 지정
export AWS_PROFILE="$PROFILE_NAME"

# 이미 생성되어 있는 고정 버킷명을 변수에 바로 할당합니다.
BUCKET_NAME="tfstate-bucket-95ada58e"

echo " 고정된 백엔드 S3 버킷 확인: $BUCKET_NAME"
echo " 테라폼 초기화를 진행합니다... "

terraform init
# 이미 버킷이 존재하므로 에러가 날 수 있지만 || true 로 안전하게 넘어갑니다.
terraform apply -auto-approve || true

echo "📝 main 테라폼용 backend.hcl 설정 파일을 생성합니다..."

# 지정된 고정 버킷명으로 backend.hcl 파일을 생성합니다.
cat << EOF > ../init/backend.hcl
bucket = "${BUCKET_NAME}"
EOF

echo "✅ backend.hcl 생성이 완료되었습니다. (적용된 버킷: $BUCKET_NAME)"

echo "============================================================="
echo "✅ 모든 초기 설정 및 backend.hcl 연동이 성공적으로 완료되었습니다!"
echo "============================================================="