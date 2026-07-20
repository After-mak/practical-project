#!/usr/bin/env bash
set -euo pipefail

# Sample FastAPI 전용 ECR을 생성하고 동일 이미지를 API와 Worker Deployment에 적용합니다.
# Prometheus Target과 KEDA 리소스는 이 스크립트의 범위에 포함하지 않습니다.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TF_DIR="${ROOT_DIR}/infra/terraform/envs/dev"
TFVARS_FILE="${ROOT_DIR}/infra/terraform/terraform.tfvars"

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-project03-eks}"
NAMESPACE="sample-fastapi"
IMAGE_TAG="${IMAGE_TAG:-v0.1.0}"
QUEUE_KEY="${QUEUE_KEY:-dev:sample:queue}"

if [[ -z "${AWS_PROFILE:-}" && -f "${TFVARS_FILE}" ]]; then
  AWS_PROFILE="$(awk -F'"' '/^[[:space:]]*aws_profile[[:space:]]*=/{print $2; exit}' "${TFVARS_FILE}")"
  export AWS_PROFILE
fi

for command_name in aws docker terraform kubectl sed; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 1
  fi
done

echo "[1/8] AWS identity 확인"
aws sts get-caller-identity >/dev/null

echo "[2/8] Terraform Backend와 Module 초기화"
terraform -chdir="${TF_DIR}" init -reconfigure -backend-config=backend.hcl

echo "[3/8] Sample FastAPI 전용 ECR 생성"
# Root Module의 RDS/Tailscale 변수는 필수로 선언돼 있지만 ECR Target과는 무관합니다.
# 불필요한 Secret 입력을 피하도록 이 Target Apply에만 사용되지 않는 값을 전달합니다.
terraform -chdir="${TF_DIR}" apply \
  -var-file="${TFVARS_FILE}" \
  -var="db_user=ecr-target-unused" \
  -var="db_password=ecr-target-unused" \
  -var="tailscale_auth_key=ecr-target-unused" \
  -target=module.sample_fastapi_ecr

ECR_REPOSITORY_URL="$(terraform -chdir="${TF_DIR}" output -raw sample_fastapi_ecr_repository_url)"
REDIS_HOST="$(terraform -chdir="${TF_DIR}" output -raw redis_primary_endpoint)"
IMAGE_URI="${ECR_REPOSITORY_URL}:${IMAGE_TAG}"

echo "[4/8] Docker 이미지 Build"
docker build --pull -t "sample-fastapi:${IMAGE_TAG}" "${ROOT_DIR}/apps/sample-fastapi"

echo "[5/8] ECR 로그인 및 이미지 Push"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REPOSITORY_URL%%/*}"
docker tag "sample-fastapi:${IMAGE_TAG}" "${IMAGE_URI}"
docker push "${IMAGE_URI}"
aws ecr describe-images \
  --region "${AWS_REGION}" \
  --repository-name sample-fastapi \
  --image-ids imageTag="${IMAGE_TAG}" \
  --query 'imageDetails[0].{Digest:imageDigest,Tags:imageTags,Size:imageSizeInBytes}'

echo "[6/8] EKS kubeconfig 갱신"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${EKS_CLUSTER_NAME}"
kubectl get nodes

echo "[7/8] Namespace와 ElastiCache ConfigMap 적용"
kubectl apply -f "${SCRIPT_DIR}/namespace.yaml"
kubectl -n "${NAMESPACE}" create configmap sample-fastapi-config \
  --from-literal=REDIS_HOST="${REDIS_HOST}" \
  --from-literal=REDIS_PORT="6379" \
  --from-literal=REDIS_DB="0" \
  --from-literal=REDIS_SSL="true" \
  --from-literal=REDIS_SSL_CERT_REQS="required" \
  --from-literal=REDIS_CONNECT_TIMEOUT="5" \
  --from-literal=REDIS_SOCKET_TIMEOUT="5" \
  --from-literal=REDIS_HEALTH_CHECK_INTERVAL="30" \
  --from-literal=REDIS_RETRY_ATTEMPTS="2" \
  --from-literal=REDIS_QUEUE_KEY="${QUEUE_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[8/8] 정식 FastAPI와 Worker Deployment 적용"
sed "s|sample-fastapi:replace-me|${IMAGE_URI}|g" "${SCRIPT_DIR}/fastapi-deployment.yaml" \
  | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/fastapi-service.yaml"
sed "s|sample-fastapi:replace-me|${IMAGE_URI}|g" "${SCRIPT_DIR}/worker-deployment.yaml" \
  | kubectl apply -f -

echo "FastAPI Rollout 확인"
kubectl -n "${NAMESPACE}" rollout status deployment/sample-fastapi --timeout=180s
kubectl -n "${NAMESPACE}" get deployment,pod,service,configmap

echo "Deployment complete: ${IMAGE_URI}"
echo "Worker replicas remain at 0 until Queue Length 3 is verified."
