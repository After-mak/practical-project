#!/usr/bin/env bash
set -euo pipefail

# init Root Module에서 생성한 sample-fastapi ECR을 조회한 뒤 API와 Worker 이미지를 Push합니다.
# 이 스크립트의 kubectl apply 구간은 Argo CD 전환 전 수동 배포 및 장애 복구 용도입니다.

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

for command_name in aws docker terraform kubectl sed grep; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 1
  fi
done

echo "[1/8] AWS identity 확인"
aws sts get-caller-identity >/dev/null

echo "[2/8] Terraform Backend와 Module 초기화"
terraform -chdir="${TF_DIR}" init -reconfigure -backend-config=backend.hcl

echo "[3/8] init에서 생성한 Sample FastAPI ECR 확인"
if ! ECR_REPOSITORY_URL="$(aws ecr describe-repositories \
  --region "${AWS_REGION}" \
  --repository-names sample-fastapi \
  --query 'repositories[0].repositoryUri' \
  --output text 2>/dev/null)"; then
  echo "sample-fastapi ECR Repository가 없습니다." >&2
  echo "먼저 infra/terraform/init에서 terraform apply를 실행하세요." >&2
  exit 1
fi

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

echo "[8/8] FastAPI와 Worker Deployment 적용"
sed "s|sample-fastapi:replace-me|${IMAGE_URI}|g" "${SCRIPT_DIR}/fastapi-deployment.yaml" \
  | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/fastapi-service.yaml"
sed "s|sample-fastapi:replace-me|${IMAGE_URI}|g" "${SCRIPT_DIR}/worker-deployment.yaml" \
  | kubectl apply -f -
kubectl apply -f "${SCRIPT_DIR}/worker-service.yaml"

# kube-prometheus-stack이 설치된 경우에만 ServiceMonitor를 적용합니다.
if kubectl api-resources --api-group=monitoring.coreos.com -o name \
  | grep -qx 'servicemonitors.monitoring.coreos.com'; then
  kubectl apply -f "${SCRIPT_DIR}/fastapi-servicemonitor.yaml"
  kubectl apply -f "${SCRIPT_DIR}/worker-servicemonitor.yaml"
else
  echo "ServiceMonitor CRD not found; install/sync kube-prometheus-stack and apply the monitors later."
fi

echo "FastAPI Rollout 확인"
kubectl -n "${NAMESPACE}" rollout status deployment/sample-fastapi --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deployment/sample-worker --timeout=180s
kubectl -n "${NAMESPACE}" get deployment,pod,service,configmap

echo "Deployment complete: ${IMAGE_URI}"
echo "Worker keeps one baseline replica. KEDA minReplicaCount must also be 1."
