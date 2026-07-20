# =============================================================
# 파일위치 : /home/user1/practical-project/Makefile
# 일과후 막걸리 팀 프로젝트 Makefile
# 사용법: 프로젝트 폴더(/home/user1/practical-project)에서  make [명령어]
# =============================================================

# ── 경로 및 환경 변수 설정 ──────────────────────────────────
TF_DEV_DIR   := infra/terraform/envs/dev
TF_INIT_DIR  := infra/terraform/init
ANSIBLE_DIR  := infra/ansible
TF_VARS_FILE := infra/terraform/terraform.tfvars

# tfvars 파일에서 aws_profile 값을 자동으로 추출 (예: admin-jongwon)
AWS_PROF := $(shell grep "aws_profile" $(TF_VARS_FILE) 2>/dev/null | cut -d'"' -f2)
# PROFILE_NAME에서 admin-을 제외한 유저명 추출
CURRENT_USER := $(shell echo "$(AWS_PROF)" | sed 's/admin-//')

# ⭐ Makefile 안에서 실행되는 모든 명령에 AWS_PROFILE을 자동으로 주입
export AWS_PROFILE := $(AWS_PROF)

# 모든 명령어를 .PHONY에 등록하여 파일 이름 충돌 방지 (가독성을 위해 분할)
.PHONY: help setup check init fmt validate plan apply apply-auto output destroy


# 기본 명령어 (명령어 없이 make만 쳤을 때 가이드 출력)
help:
	@echo "============================================================="
	@echo "🍶 일과후 막걸리 팀 프로젝트 통합 관리 스크립트"
	@echo "============================================================="
	@echo " 👉 현재 접속 프로필: [ $(AWS_PROFILE) ] (유저명: $(CURRENT_USER))"
	@echo "============================================================="
	@echo " [Terraform - AWS 인프라]"
	@echo "  make setup         : 최초 1회 본인 전용 AWS 프로필 설정 및 S3/DynamoDB 생성"
	@echo "  make init          : 테라폼 초기화"
	@echo "  make fmt           : 코드 스타일 정렬"
	@echo "  make validate      : 문법 검사"
	@echo "  make plan          : 인프라 변경사항 시뮬레이션"
	@echo "  make apply-auto    : AWS 실제 배포 (승인)"
	@echo "  make apply-auto    : AWS 실제 배포 (승인 생략)"
	@echo "  make output        : 배포된 AWS 인프라 정보 확인"
	@echo "  make destroy       : AWS 인프라 전체 삭제"
	@echo "============================================================="


# ── 초기 설정 ─────────────────────────────────────────────────
setup:
	@chmod +x setup.sh
	./setup.sh
check:
	@chmod +x check.sh
	./check.sh

# ── Terraform ────────────────────────────────────────────────
init:
	@echo "▶ 테라폼 백엔드 초기화 중..."
	cd $(TF_DEV_DIR) && terraform init -backend-config=backend.hcl

fmt:
	@echo "▶ 테라폼 코드 포맷 정렬 중..."
	cd $(TF_DEV_DIR) && terraform fmt -recursive

validate:
	@echo "▶ 테라폼 문법 및 유효성 검사 중..."
	cd $(TF_DEV_DIR) && terraform validate

plan:
	@echo "▶ AWS 인프라 변경 예측(Plan) 실행 중..."
	cd $(TF_DEV_DIR) && terraform plan

apply:
	@echo "▶ AWS 인프라 실배포 진행 중 (수동 승인 필요)..."
	cd $(TF_DEV_DIR) && terraform apply -parallelism=3

apply-auto:
	@echo "▶ AWS 인프라 고속 자동 배포 중 (FinOps 적용)..."
	cd $(TF_DEV_DIR) && terraform apply --auto-approve -parallelism=3

output:
	@echo "▶ 배포된 AWS 리소스 정보(ALB/EKS/ECR/WAF) 출력..."
	cd $(TF_DEV_DIR) && terraform output

destroy:
	@echo "⚠️  주의: AWS 인프라 자원 삭제중..."
	cd $(TF_DEV_DIR) && terraform destroy --auto-approve 


# ── Ansible ───────────────────────────────────────────────────	



# ── GitOps  ───────────────────────────────────────────────────



