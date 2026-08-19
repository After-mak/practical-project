# Bank of Anthos JWT 키 교체 절차

## 현재 판정

기존 JWT Private Key는 Git 추적 파일, Terraform/Argo CD Application values, 그리고 클러스터 리소스 메타데이터 경로에 노출된 이력이 있습니다. 실제 값은 이 문서에 기록하지 않습니다. 기존 키는 폐기 대상으로 간주해야 합니다.

## 승인 전 준비 상태

- 새 AWS Secrets Manager 이름: project03/bank-of-anthos/jwt-v2
- 새 Kubernetes Secret 이름: bank-jwt-key-v2
- 필수 JSON 키 이름: jwtRS256.key, jwtRS256.key.pub
- Terraform이 먼저 생성·관리하는 대상 Namespace: frontend, backend
- Chart는 Secret을 생성하지 않고 secrets.existingSecret만 참조합니다.

## 승인 후 교체 순서

1. 인터넷과 셸 이력에 키를 남기지 않는 안전한 단말에서 새 RSA 키 쌍을 생성합니다.
2. 새 키 쌍을 AWS Secrets Manager project03/bank-of-anthos/jwt-v2에 저장합니다.
3. 이 디렉터리에서 Terraform plan을 검토합니다.
4. Frontend와 Backend Application의 자동 동기화를 일시 보류하고 현재 상태를 기록합니다.
5. Terraform이 frontend/backend Namespace를 만든 뒤 kubernetes_secret_v1.bank_jwt 두 리소스를 생성하는지 확인하고, 값 대신 Secret 이름과 데이터 키 이름만 검증합니다.
6. 동기화가 보류된 상태에서 mak-argocd-deploy Chart와 argocd_deploy Application values를 모두 준비하고 diff를 확인합니다.
7. 새 Chart와 existingSecret=bank-jwt-key-v2 전환을 같은 변경 창에서 동기화합니다.
8. Frontend/Backend Pod가 모두 bank-jwt-key-v2를 참조하고 Ready인지 확인합니다.
9. 로그인, 토큰 발급, 잔액/이력/송금 핵심 동작을 확인합니다.
10. 자동 동기화를 복구한 뒤 기존 jwt-key와 Argo CD Application 내 평문 values가 제거됐는지 값 비노출 방식으로 확인합니다.
11. Terraform state 버전, Git 이력, Argo CD 감사 로그 접근을 제한하고 필요 시 이력 정리 절차를 별도로 승인받습니다.

## 서비스 영향과 롤백

키를 읽는 프로세스가 시작 시점에 값을 고정하면 Pod 재시작이 필요합니다. Private/Public Key가 서로 다른 시점에 적용되면 로그인이나 서비스 간 JWT 검증이 실패할 수 있으므로 두 Namespace를 같은 변경 창에서 교체해야 합니다. 기존 키는 노출된 것으로 간주하므로 보안 롤백 대상으로 재사용하지 않습니다. 기능 문제가 생기면 새 키를 유지한 채 Chart와 애플리케이션 설정만 직전 정상 Revision으로 되돌리거나, 별도 v3 키를 발급해 같은 절차로 다시 교체합니다.

## 금지 사항

- 키 본문을 Git, tfvars, Helm values, Argo CD Application, 로그, Markdown에 넣지 않습니다.
- 승인 없이 AWS Secret 생성/변경, Terraform apply, Pod 재시작을 수행하지 않습니다.
- kubectl get secret -o yaml/json처럼 data 또는 last-applied annotation을 출력하는 명령을 사용하지 않습니다.
