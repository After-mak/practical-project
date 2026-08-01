### 버전이 안 맞아서 init이나 plan 실패시 대처방법

```bash
terraform init -upgrade

```

### Error: Backend configuration changed 대처방법

```bash
[user1@mgmt infra]$ terraform init -reconfigure -backend-config="profile=admin-프로필명"
```

### init
AWS_PROFILE=admin-jongwon terraform apply \
  -target=module.ecr \
  -target=module.ecr_frontend \
  -target=module.ecr_balancereader \
  -target=module.ecr_ledgerwriter \
  -target=module.ecr_userservice \
  -target=module.ecr_contacts \
  -target=module.ecr_transactionhistory \
  -target=module.finops_analyzer_ecr \
  -target=module.krr_demo_seed_ecr \
  -target=module.sample_fastapi_ecr \
  -target=module.tg_gateway_ecr \
  -auto-approve